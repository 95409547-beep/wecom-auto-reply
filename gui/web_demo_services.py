"""In-memory review fixtures; never imports configuration or customer stores."""
from copy import deepcopy
from datetime import date, timedelta
from gui.web_services import revision


class DemoServices:
    def __init__(self):
        self.archive = "game"
        self.archives = [{"id": "game", "name": "游戏客服知识库"}, {"id": "demo", "name": "产品演示资料"}]
        self.rows = []
        for i, (q, a, source) in enumerate([
            ("账号无法登录怎么办？", "请先核对游戏区服与账号信息，并提供订单编号和登录报错截图。请勿连续尝试登录，核实后由人工继续处理。", "账号售后.md"),
            ("购买后多久可以收到账号？", "请提供订单编号，由人工核查交付进度。未查询订单前不承诺具体交付时间。", "订单交付.md"),
            ("这个账号支持改绑吗？", "改绑方式以具体账号的商品说明为准。请提供商品链接后核实。", "账号售后.md"),
            ("游戏充值没有到账怎么处理？", "请提供游戏角色 ID、区服、支付时间与支付凭证，交由人工核查充值记录。", "充值问题.md"),
            ("购买前能查看账号的详细信息吗？", "可以先查看商品说明中的角色信息。如需核实其他内容，请发送商品链接。", "购买须知.md"),
            ("如何联系人工售后？", "请在当前会话描述问题，并提供订单编号，人工客服会在此继续跟进。", "售后流程.md"),
        ]):
            text = f"客户问题：{q}\n销售回答：{a}"
            self.rows.append(dict(id=str(i), question=q, answer=a, text=text, source=source, faq=True, revision=revision(text)))
        self.prompts = [dict(key=key, label=label, required=["{context}"] if key == "system" else [], text=text, revision=revision(text)) for key, label, text in [
            ("system", "业务回复提示词", "你是一名游戏账号售后客服。\n\n先确认客户的具体问题，再使用以下资料回答。\n{context}\n\n回复要求\n1. 只使用资料中的事实，不猜测价格、交付时间与售后政策。\n2. 句子简洁、语气自然，避免连续反问。\n3. 资料不足时交由人工处理。"),
            ("smalltalk", "闲聊提示词", "用简洁、自然的语气回应客户，避免重复欢迎语。"),
            ("hold", "占位语提示词", "收到，我帮您核对一下，请稍等。"),
            ("tone_samples", "口吻样本", "您好，麻烦您提供一下订单编号，我帮您查看。\n收到，我这边核实后回复您。"),
            ("welcome", "欢迎语", "您好，请问有什么可以帮您？"),
            ("nontext", "非文本应答", "图片：图片已收到，我帮您查看。")]]
        self.records = [dict(timestamp=f"{date.today()} 14:{48-i*3:02d}", customer=["林先生", "陈女士", "小周"][i%3], message=r["question"], reply=r["answer"], action=["auto_send", "hold", "replied"][i%3]) for i,r in enumerate(self.rows)]
        self.learned = [dict(id="1", kind="style_rules", label="语气规则", text="确认问题后再索要订单信息，避免一次连续询问多个问题。", hits=8),dict(id="2", kind="tone_samples", label="口吻样本", text="收到，我这边核实后在这里回复您。", hits=5)]
        self.facts = [dict(id="fact1", question="改绑前需要提供什么资料？", claim="请先提供商品链接与订单编号，由人工核查账号的改绑要求。", source="人工改稿", ts="2026-11-16 13:24")]
        self.enabled = True
        self.model_saved = False
        self.values = dict(llm_base_url="https://api.deepseek.com/v1",llm_model="deepseek-chat",llm_api_key="",wecom_corp_id="",wecom_kf_secret="",wecom_open_kfid="",software="wecom")

    def read(self, name, p):
        common = dict(archive=self.archive, archives=deepcopy(self.archives))
        if name == "records":
            return {"rows": deepcopy(self.records)}
        if name == "knowledge":
            rows = [r for r in self.rows if p.get("query", "") in r["text"]]
            return {**common, "rows": deepcopy(rows), "total": len(rows), "files": [{"name": "账号售后.md", "size_kb": 8.4, "mtime": "2026-11-16 10:20"}]}
        if name == "prompts":
            return {**common, "prompts": deepcopy(self.prompts), "safety": "不编造价格、库存、政策与时间承诺。\n\n业务事实必须来自资料库。\n\n资料不足时交由人工处理，不向客户提供未经核实的信息。"}
        if name == "learned":
            return {**common, "rows": deepcopy(self.learned), "facts": deepcopy(self.facts), "counts": dict(rules=1,tones=1,blocked=0,accepts=13), "enabled": self.enabled, "preview": "\n".join(r["text"] for r in self.learned) if self.enabled else ""}
        if name == "probe":
            return common
        if name == "unanswered":
            return {**common, "rows": [dict(question="账号换绑后原设备还能登录吗？", reason="缺少对应资料", count=7, last_ts=1794816000, done_ts=None)], "total": 7, "todo": 1}
        if name == "settings":
            return dict(values=deepcopy(self.values), savedSecrets={"llm_api_key": self.model_saved}, presets=[("DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat"),("自定义接口", "", "")], channels=[("wecom", "企业微信 · 截图模式", True, "通过桌面窗口采集与回复"),("wecom_api", "企业微信 · 微信客服 API", True, "通过官方 API 接入，无需保持桌面窗口"),("wechat", "个人微信", False, "需要先完成窗口标定")])
        if name == "dashboard":
            return dict(replies=128,auto=96,hold=32,customers=43,pending_now=5,median_reply_seconds=2.4,solve_rate=.75,buckets=[dict(label=f"{9+i}:00",replies=v,auto=int(v*.75)) for i,v in enumerate([3,9,18,12,23,28,21,14])],by_path={"正常直答":96,"资料不足":24,"需要人工判断":8},sample_messages={"正常直答":[r["question"] for r in self.rows]},unanswered_top=[dict(question="账号换绑后原设备还能登录吗？",count=7,reason="缺少对应资料"),dict(question="退款申请需要多久审核？",count=4,reason="政策需人工核实")],export_rows=[dict(ts=r["timestamp"],customer=r["customer"],message=r["message"],source=r["action"],path="正常直答",reply=r["reply"]) for r in self.records])
        raise ValueError("页面不存在")

    def command(self, action, p):
        message = "演示操作已完成，未修改真实数据"
        if action == "records.clear": self.records.clear()
        elif action == "archive.switch": self.archive = p["id"]
        elif action == "prompt.save":
            row = next(r for r in self.prompts if r["key"] == p["key"])
            if row["key"] == "system" and "{context}" not in p["text"]: raise ValueError("必须保留 {context} 占位符")
            row.update(text=p["text"],revision=revision(p["text"]))
        elif action == "kb.add":
            text = p.get("question", "") + "\n" + p["answer"]
            self.rows.append(dict(id=str(len(self.rows)),question=p.get("question", ""),answer=p["answer"],text=text,faq=True,revision=revision(text),source="手动添加"))
        elif action == "kb.edit":
            row = next(r for r in self.rows if r["id"] == p["id"])
            text = p.get("question", "") + "\n" + p["answer"]
            row.update(question=p.get("question", ""),answer=p["answer"],text=text,revision=revision(text))
        elif action == "kb.delete": self.rows = [r for r in self.rows if r["id"] != p["id"]]
        elif action == "learn.toggle": self.enabled = bool(p["enabled"])
        elif action in ("learn.delete", "learn.block"): self.learned = [r for r in self.learned if r["id"] != p["id"]]
        elif action in ("fact.accept", "fact.reject"): self.facts = [r for r in self.facts if r["id"] != p["id"]]
        elif action == "probe.run": return dict(hits=[{**deepcopy(self.rows[0]),"score":.86,"verdict":"高于自动回复阈值"}],threshold=.75,message="演示检索完成")
        elif action == "settings.models": return dict(models=["deepseek-chat","deepseek-reasoner"],message="已读取演示模型列表")
        elif action in ("settings.save", "settings.test_save"):
            values = p["values"]
            self.model_saved = bool(values.get("llm_api_key")) or (
                self.model_saved and not p.get("clearSecrets", {}).get("llm_api_key"))
            self.values.update({**values, "llm_api_key": "", "wecom_kf_secret": ""})
            message = "演示连接成功，演示设置已保存" if action == "settings.test_save" else "演示设置已保存"
        elif action in ("settings.test", "settings.wecom_test"): message = "演示连接成功（未请求外部接口）"
        elif action in ("exit", "restart"): message = "演示模式不会退出或重启真实程序"
        else: raise ValueError("此演示未模拟该操作，请在正式程序中使用。")
        return {"message": message, "software_changed": False}
