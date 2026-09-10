# Changelog

## 2.2.0

- 改为真正的 Windows 安装包构建工程。
- 安装后可从桌面图标直接启动，不依赖 BAT。
- PyInstaller 使用 onedir 方式打包，降低单文件自解压和杀软误报风险。
- Inno Setup 输出 `DouRPA_Setup.exe`。
- RPA 优先调用系统 Microsoft Edge，不额外捆绑 Chromium。
- 用户数据迁移到 `%LOCALAPPDATA%\DouRPA`，避免 Program Files 写权限问题。
- 保留相似品批量发布：标题、第一张主图、SKU 名称三个字段修改边界。
