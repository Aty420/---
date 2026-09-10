# DouRPA Pro — 抖店相似品批量发布 RPA

这是 Windows 本地桌面应用的构建工程。目标交付形态是 `DouRPA_Setup.exe`：双击安装，安装后桌面生成 **DouRPA Pro** 图标，用户电脑不需要单独安装 Python。

## 当前自动化边界

软件严格围绕已有商品的“发布相似品”流程：

`搜索源商品 → 发布相似品 → 修改标题 → 仅替换第 1 张主图 → 修改 SKU/规格名称 → 发布前一致性校验 → 提交 → 检测提交成功`

默认不主动修改类目、品牌、商品属性、详情页、第 2 张及以后主图、价格、库存、物流和发货时效。

首次运行某个店铺时，由用户本人在打开的 Edge 浏览器中扫码/完成安全验证。软件不绕过验证码、滑块或平台安全校验。每个店铺使用独立浏览器 Profile 保存登录状态。

## 自动生成 Windows 安装包

仓库内置 `.github/workflows/build-windows.yml`。文件推送到 `main` 后，GitHub Actions 会自动：

1. 在 `windows-latest` 安装 Python 3.12 和依赖；
2. 使用 PyInstaller 生成 Windows 桌面程序；
3. 使用 Inno Setup 生成 `DouRPA_Setup.exe`；
4. 把安装包上传到该次 Actions 运行的 **Artifacts**。

构建完成后，进入 GitHub 仓库顶部 **Actions** → 打开最新一次 `Build Windows Installer` → 页面底部 **Artifacts** → 下载 `DouRPA-Windows-Installer`，解压即可得到 `DouRPA_Setup.exe`。

## 本地数据位置

安装目录只保存程序。可写数据统一放在：

`%LOCALAPPDATA%\DouRPA`

其中包含：

- `data/app.db`：任务、店铺、模板、日志数据库
- `data/profiles/`：每个店铺独立 Edge 登录 Profile
- `config/selectors.json`：抖店页面元素定位配置
- `samples/相似品批量任务模板.xlsx`：任务导入模板
- `screenshots/`：RPA 失败截图
- `logs/`：运行日志目录

## 首次实机校准

RPA 的业务顺序已按录制流程固化，但抖店后台 DOM 会因账号、灰度版本和页面升级存在差异。首次使用建议开启“发布前安全停点”，先运行 1 条任务；如果某个控件定位失败，只需要校准 `%LOCALAPPDATA%\DouRPA\config\selectors.json` 对应节点，不需要重做整套程序。
