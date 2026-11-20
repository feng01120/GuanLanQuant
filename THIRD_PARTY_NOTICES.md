# 第三方依赖与许可证说明

观澜 QuantDesk 的源码采用 MIT License。打包后的 Windows 发行版还包含以下第三方组件，它们分别遵循自己的许可证；发行时不得删除其许可证文本。

| 组件 | 用途 | 许可证 |
| --- | --- | --- |
| PySide6 / Qt for Python | 桌面界面与 Qt 运行时 | LGPL-3.0（动态链接；见 Qt for Python 发行说明） |
| pyqtgraph | 行情与指标绘图 | MIT |
| NumPy | 数值计算 | BSD-3-Clause |
| pandas | 时间序列与表格处理 | BSD-3-Clause |
| SciPy | 统计与分布计算 | BSD-3-Clause |
| scikit-learn | 机器学习模型 | BSD-3-Clause |
| requests | HTTP 数据源访问 | Apache-2.0 |

数据来源包括东方财富、腾讯、新浪、国家统计局、中国人民银行、巨潮资讯等公开接口；行情与资讯的版权归原数据提供方所有。本项目只做研究性聚合与统计展示，不构成投资建议。

如果重新分发 PyInstaller 打包产物，请同时保留 PySide6/Qt 的 LGPL 许可证与对应第三方许可证文件。
