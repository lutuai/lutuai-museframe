# 提示词与验收模板

仅在需要组织复杂编辑、批量任务或排查失败时读取。本文件不要求用户逐项填写。

## 编辑提示词骨架

```text
Task: Edit the attached CONTENT SOURCE image into [chosen medium].
Input roles: Image A is the content and identity source. [Image B, if present, is only a material/palette reference.]
Content anchors: [observed subject count, identity features, objects, relative positions, occlusions].
Layout: [preserve original framing and aspect ratio / user-approved poster layout].
Material translation: [surface, mark-making, edges, lighting, palette from the selected recipe].
Strength: [low / medium / high expressed as concrete allowed changes].
Must preserve: [identity, silhouette, meaningful details, user requirements].
Do not introduce: [people, objects, props, letters, signatures, source-unrelated elements].
Text: [retain exact text / user-authorized removal / no new text].
Output: One complete image, [requested aspect ratio], no comparison board unless requested.
```

主体卡是观察结果，不是仅靠文字重建照片的替代品。实际调用仍必须携带原图。

## 常见失败与修正

| 发现的问题 | 下一次修正重点 |
| --- | --- |
| 人物像换了一个人 | 原图重新作为身份来源，降低脸部简化，描述可见辨识点，保持姿态 |
| 猫狗斑纹丢失 | 指定斑纹的所在部位、颜色和不对称关系，避免用“可爱宠物”覆盖细节 |
| 横图被变成竖版 | 明确原图比例和完整取景，取消风格配方中的自动裁切与留白 |
| 材质变化不明显 | 加强具体笔触/叠纸/针脚，保留主体卡，不用加新物件制造风格 |
| 增加花、鸟或装饰文字 | 明确这些元素不在内容原图，风格参考只提供材质 |
| 杯子、栏杆、窗户变形 | 针对结构问题局部编辑，避免重生成整张导致其他区域漂移 |
| 文字出现伪字 | 对精确文字使用可编辑排版工具后期放置，或告知无法可靠重现 |

若用户要求真实印刷尺寸，确认像素尺寸与印刷要求；仅写入 DPI 元数据不会增加细节。只报告工具实际提供的分辨率。

## 执行记录

需要可追溯交付时，记录每张结果的源图、风格 ID、提示词、实际工具名称、最终文件、查看状态、验收问题。没有真正执行的步骤标记 pending；未查看的项目标记 not_reviewed。不编造 seed、模型参数、耗时或验收分数。

批量任务可在 `job.json` 旁另写 `results.json`；原计划与实际记录各自保留。失败项附原因，成功项不反复重做。
