#!/usr/bin/env python3
"""Prepare reference-image transformation jobs. No image is generated here."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
import sys
import tempfile
from pathlib import Path


STYLE_PATH = Path(__file__).resolve().parent.parent / "references" / "styles.json"
SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
STRENGTHS = {
    "low": (
        "Apply a restrained treatment: keep source forms, facial features and "
        "small identifying details clear; let the medium show mainly through "
        "surface texture, restrained marks and modest colour interpretation."
    ),
    "medium": (
        "Make the selected medium clearly visible through texture, marks and "
        "colour relationships. Simplify secondary detail while keeping all "
        "subject silhouettes and identifying features legible."
    ),
    "high": (
        "Make a pronounced interpretation of the selected medium with stronger "
        "marks and selective abstraction. Preserve subject count, identity "
        "cues, silhouettes, spatial relationships and the actual scene; a "
        "strong treatment is not permission to invent or replace content."
    ),
}


class JobError(ValueError):
    """A validation problem that should be shown without a traceback."""


def load_styles(path: Path = STYLE_PATH) -> dict[str, dict]:
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise JobError(f"Cannot read the style registry: {exc}") from exc
    entries = document.get("styles") if isinstance(document, dict) else None
    if not isinstance(entries, list) or not entries:
        raise JobError("The style registry must contain a nonempty 'styles' array.")
    registry: dict[str, dict] = {}
    text_fields = (
        "id", "name_en", "name_zh", "surface", "marks", "edges", "lighting",
        "simplify", "preserve", "prompt_en",
    )
    for entry in entries:
        if not isinstance(entry, dict):
            raise JobError("Every style must be an object.")
        for field in text_fields:
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise JobError(f"A style is missing a nonempty text field: {field}")
        for field in ("fit", "palette", "avoid"):
            value = entry.get(field)
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                raise JobError(f"Style {entry['id']!r}: {field} must be a string array.")
        if entry["id"] in registry:
            raise JobError(f"Duplicate style ID: {entry['id']}")
        registry[entry["id"]] = entry
    return registry


def validate_image(raw_path: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        raise JobError(f"Source image does not exist or is not a file: {path}")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise JobError(f"Unsupported image extension: {path.name}; use PNG, JPG, JPEG or WebP.")
    try:
        with path.open("rb") as stream:
            header = stream.read(32)
        size = path.stat().st_size
    except OSError as exc:
        raise JobError(f"Cannot read source image {path}: {exc}") from exc

    # This is file-header validation, not a complete image decoder. The actual
    # reference-image tool must still decode and inspect the supplied image.
    is_png = (
        size >= 45
        and len(header) >= 24
        and header[:8] == b"\x89PNG\r\n\x1a\n"
        and header[8:16] == b"\x00\x00\x00\rIHDR"
        and all(struct.unpack(">II", header[16:24]))
    )
    is_jpeg = size >= 4 and header[:3] == b"\xff\xd8\xff"
    is_webp = (
        size >= 20
        and header[:4] == b"RIFF"
        and header[8:12] == b"WEBP"
        and header[12:16] in (b"VP8 ", b"VP8L", b"VP8X")
        and struct.unpack("<I", header[4:8])[0] + 8 <= size
    )
    matches_extension = (
        (suffix == ".png" and is_png)
        or (suffix in (".jpg", ".jpeg") and is_jpeg)
        or (suffix == ".webp" and is_webp)
    )
    if not matches_extension:
        raise JobError(f"Invalid image header or extension/content mismatch: {path.name}")
    return path


def slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")[:64] or "image"


def make_prompt(style: dict, strength: str, layout: str, ratio: str, anchors: str) -> str:
    if layout == "preserve":
        composition = (
            "Keep the source aspect ratio, framing and composition. Do not crop "
            "away subjects, reposition them, add borders, or convert this into "
            "a poster. Preserve the source background layout and perspective."
        )
    else:
        requested_ratio = "the source aspect ratio" if ratio == "source" else f"a {ratio} aspect ratio"
        composition = (
            f"Create a poster composition at {requested_ratio}. Treat the source "
            "scene as one intact unit: any scaling or placement must preserve "
            "the subjects' positions relative to each other. Do not crop away "
            "people or key objects. Use quiet, nonrepresentational negative "
            "space when the requested frame needs extra room; do not invent "
            "scene content to extend the photograph. Do not add typography, "
            "logos, watermarks or decorative objects."
        )
    anchors_section = (
        "\nUSER-SUPPLIED VISUAL ANCHORS\n"
        "Use these notes to identify details in the source. If a note conflicts "
        "with the visible source, retain the visible source rather than "
        "inventing the described detail.\n"
        f"--- BEGIN ANCHOR NOTES ---\n{anchors}\n--- END ANCHOR NOTES ---\n"
        if anchors else ""
    )
    palette = ", ".join(style["palette"])
    avoid = "; ".join(style["avoid"])
    return (
        "REFERENCE-IMAGE TRANSFORMATION REQUEST\n\n"
        "REQUIRED ATTACHMENT\n"
        "The operator must attach the actual source image identified by this "
        "task's source field in job.json to an image tool that explicitly "
        "supports image references or image editing. This text alone is not a "
        "valid substitute for the source attachment. If that capability is "
        "unavailable, stop and request a compatible tool; do not pretend to "
        "have generated or edited an image.\n"
        "Attachment role: SOURCE is the user's photograph and the sole "
        "authority for scene content, subjects and composition. Gallery images, "
        "style illustrations and documentation examples are not SOURCE. Do not "
        "treat an example image as the user's input or transfer its subjects "
        "or layout into this scene.\n\n"
        "TRANSFORMATION\n"
        f"Interpret SOURCE as {style['name_en']} ({style['name_zh']}).\n"
        f"{style['prompt_en']}\n"
        f"Surface: {style['surface']}\n"
        f"Mark making: {style['marks']}\n"
        f"Edges: {style['edges']}\n"
        f"Lighting: {style['lighting']}\n"
        f"Palette direction: {palette}. Use this as a relationship guide, "
        "preserving source colour cues that identify the subjects.\n"
        f"Simplification: {style['simplify']}\n"
        f"Style-specific preservation: {style['preserve']}\n"
        f"Avoid: {avoid}\n\n"
        "CONTENT AND STRUCTURE\n"
        "Preserve the number of people, animals and important objects; their "
        "positions and spatial relationships; body proportions, silhouettes, "
        "poses, clothing and distinguishing visible features. Preserve object "
        "outlines and major architecture. Do not insert, remove, duplicate or "
        "replace a subject. Do not add objects absent from the source. Keep "
        "uncertain or occluded details understated instead of inventing them. "
        "Identity and structural consistency are objectives to inspect in "
        "the result, not guarantees made by this prompt.\n"
        "Preserve meaningful text already visible in SOURCE, including its "
        "wording and placement, unless the user explicitly requests a change. "
        "If exact lettering cannot be reproduced, report that limitation; "
        "do not present invented or garbled lettering as accurate.\n\n"
        "TREATMENT STRENGTH\n"
        f"{strength}: {STRENGTHS[strength]}\n\n"
        "LAYOUT\n"
        f"{composition}\n"
        f"{anchors_section}\n"
        "DELIVERABLE AND REVIEW\n"
        "Generate one transformed image from the attached SOURCE. Inspect it "
        "against SOURCE for subject count, identity cues, poses, silhouettes, "
        "positions, missing objects and unintended additions. If it fails "
        "these checks, revise it or clearly report the limitation. Do not "
        "claim the result is verified before that comparison has occurred.\n"
    )


def check_output(path: Path) -> None:
    if path.exists():
        if not path.is_dir():
            raise JobError(f"Output must be a new or empty directory: {path}")
        if any(path.iterdir()):
            raise JobError(f"Output directory is not empty; nothing was overwritten: {path}")


def prepare(args: argparse.Namespace, registry: dict[str, dict]) -> Path:
    if not args.input or not args.style or not args.output:
        raise JobError("Generation requires --input, --style and --output.")
    if args.layout == "preserve" and args.ratio != "source":
        raise JobError("--layout preserve requires --ratio source; use --layout poster to change aspect ratio.")
    unknown = [style_id for style_id in args.style if style_id not in registry]
    if unknown:
        raise JobError(f"Unknown style ID: {', '.join(unknown)}. Run --list-styles for valid IDs.")
    sources = [validate_image(raw_path) for raw_path in args.input]
    anchors = ""
    anchor_path = None
    if args.anchors:
        anchor_path = Path(args.anchors).expanduser().resolve()
        try:
            anchors = anchor_path.read_text(encoding="utf-8-sig").strip()
        except (OSError, UnicodeError) as exc:
            raise JobError(f"Cannot read UTF-8 visual anchors: {exc}") from exc

    output = Path(args.output).expanduser().resolve()
    if output in sources or output == anchor_path:
        raise JobError("Output must not overwrite a source image or the visual-anchor file.")
    check_output(output)
    tasks = []
    prompts = {}
    for source in sources:
        for style_id in args.style:
            task_id = f"{len(tasks) + 1:03d}"
            basename = f"{task_id}-{slug(source.stem)}-{slug(style_id)}"
            prompt_file = f"prompts/{basename}.txt"
            tasks.append({
                "id": task_id,
                "source": str(source),
                "style_id": style_id,
                "prompt_file": prompt_file,
                "suggested_output": f"images/{basename}.png",
                "status": "pending",
            })
            prompts[prompt_file] = make_prompt(
                registry[style_id], args.strength, args.layout, args.ratio, anchors
            )
    job = {
        "schema_version": "1.0",
        "status": "awaiting_image_tool",
        "settings": {
            "strength": args.strength,
            "layout": args.layout,
            "ratio": args.ratio,
            "anchors_file": str(anchor_path) if anchor_path else None,
        },
        "tasks": tasks,
    }

    # Validate everything before creating output. Stage the complete package
    # beside its final destination, then commit it as a directory.
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-staging-", dir=output.parent))
    try:
        (staging / "prompts").mkdir()
        (staging / "images").mkdir()
        for relative_path, prompt in prompts.items():
            (staging / relative_path).write_text(prompt, encoding="utf-8")
        (staging / "job.json").write_text(
            json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        check_output(output)
        if output.exists():
            output.rmdir()  # This operation refuses to remove a nonempty directory.
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return output / "job.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare local prompts and job.json for a reference-image tool; this does not generate images."
    )
    parser.add_argument("--list-styles", action="store_true", help="List style IDs and exit.")
    parser.add_argument("--input", action="append", help="Source image path; repeat for multiple photographs.")
    parser.add_argument("--style", action="append", help="Style ID; repeat for multiple styles.")
    parser.add_argument("--strength", choices=tuple(STRENGTHS), default="medium")
    parser.add_argument("--layout", choices=("preserve", "poster"), default="preserve")
    parser.add_argument("--ratio", choices=("source", "1:1", "3:4", "4:5", "16:9", "9:16"), default="source")
    parser.add_argument("--anchors", help="Optional UTF-8 text file of visual anchors, shared by every task.")
    parser.add_argument("--output", help="A new or empty output directory.")
    return parser


def main(argv: list[str] | None = None) -> int:
    # Keep Chinese style names and filenames readable when Windows redirects
    # output to a UTF-8 host, independently of the system's legacy code page.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        registry = load_styles()
        if args.list_styles:
            for style_id, style in registry.items():
                print(f"{style_id}\t{style['name_zh']} / {style['name_en']}")
            return 0
        result = prepare(args, registry)
        print(f"Prepared {len(args.input) * len(args.style)} task(s): {result}")
        print("No images were generated. Attach each task's source to a compatible reference-image tool.")
        return 0
    except (JobError, OSError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
