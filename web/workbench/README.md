# 待人工 Web 工作台

Discord 客户端风格的单页改造。保留企业微信智能客服品牌和原有业务回调。

## 使用

运行现有桌面程序，在工作台顶部点击「打开新版工作台」。页面在本机浏览器打开，
读取当前实例的待人工队列。桌面程序需要保持运行。发送、编辑后发送、忽略、开始与
停止均经过原有 Python 回调；设置、知识库、数据、全部消息、已回复在原桌面窗口打开。

本轮没有替换其他页面，没有改动消息采集、检索、生成、风控或投递逻辑。
Web 工作台尚未封装成独立 WebView 桌面窗口，也没有重新打包发布 EXE。

## 演示

在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe -m gui.web_workbench --demo
```

打开终端输出的本机地址。此模式只使用内存里的示例数据，既不导入主服务，也不读取
客户数据。操作不会发送真实消息，重启演示进程即可重置。

## 构建

```powershell
cd web/workbench
npm ci
npm run build
```

`bundle/` 是自包含资源，Python 程序运行时不需要 Node 或互联网；PyInstaller 已包含此目录。
`npm run dev` 仅提供前端开发服务，完整交互请构建后通过 Python 本机服务预览。

## 接口约束

- 仅监听 127.0.0.1；动态端口与随机会话令牌，校验 Host、Origin 和 Authorization。
- API 不启用跨域，客户数据不进入静态产物，不记录访问令牌。
- 浏览器每 800ms 读取快照；请求写入有界邮箱，由 Tk 主线程执行。
- 同一请求 ID 去重；旧消息版本、已移除条目、已入队条目不会重复提交。
- UI 保留当前会话内未发送的编辑内容，刷新页面会清空本地编辑。
- “结果待核实”继续使用原有桌面确认；“已提交发送”不代表已经送达。

## 设计

操作型界面：深灰分区、蓝紫色主要操作、单一图标库、完整原话、原位编辑、明确的发送状态。
桌面显示消息信息侧栏，小窗口保留紧凑信息条；窄屏由会话列表进入详情，导航可展开。
尊重系统的减少动画设置，动画仅用于按钮反馈和操作提示。

参考：[Refero Discord](https://styles.refero.design/style/faec4b0c-cf93-4150-97de-0a8e7eed1840)。
Unslop 方法由 [Damir Sokolovsky](https://heydamir.design/unslop) 创作，CC BY 4.0。
Inter 字体按 SIL Open Font License 使用，Phosphor Icons 按 MIT License 使用。
