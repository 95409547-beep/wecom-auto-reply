import { useEffect, useRef, useState } from 'react';
import { Robot, PaperPlaneTilt, X, CheckCircle, ArrowSquareOut } from '@phosphor-icons/react';
import './assistant.css';

export function ReplyReview({ review, run, busy, onClose, onSaved }) {
  const dialog = useRef(null);
  const saved = review.selected || [];
  const [keys, setKeys] = useState([...new Set([...saved, ...(review.proposal?.facts?.length ? ['reply'] : [])])]);
  const [error, setError] = useState('');
  useEffect(() => {
    dialog.current.showModal();
    return () => dialog.current?.close();
  }, []);
  const proposal = review.proposal || {};
  const options = [
    ...(proposal.facts || []).map(row => ({ key: row.key, label: '问答加入资料库', text: row.question + '\n' + row.claim })),
    ...(proposal.rules || []).map(row => ({ ...row, label: '学习语气习惯' })),
    ...(proposal.tone ? [{ ...proposal.tone, label: '学习口吻样本' }] : []),
  ];
  async function save() {
    setError('');
    const result = await run('page.reply.commit', { archive: review.archive, id: review.id, keys });
    if (result?.review?.status === 'learned') {
      onSaved?.();
      onClose();
    } else {
      setError('本次学习未全部完成，已保留候选，请核对状态后重试。');
    }
  }
  return <dialog className="page-dialog wide review-dialog" ref={dialog} onCancel={onClose} aria-labelledby="review-title">
    <div className="dialog-heading"><h2 id="review-title">学习这条回复</h2><button className="icon-button" aria-label="稍后处理" onClick={onClose}><X size={20}/></button></div>
    <p className="muted">回复已发送。核对适用的游戏、版本与区服，再选择要保存的内容。</p>
    {options.map(option => <label className="review-option" key={option.key}><input type="checkbox" checked={keys.includes(option.key)} disabled={busy || saved.includes(option.key)} onChange={event => setKeys(old => event.target.checked ? [...old, option.key] : old.filter(key => key !== option.key))}/><span><strong>{option.label}{saved.includes(option.key) ? ' · 已保存' : ''}</strong><pre className="prose">{option.text}</pre></span></label>)}
    {!options.length && <p>暂时没有可学习内容，可以到资料库手动补充完整问答。</p>}
    {error && <p className="inline-note error" role="alert">{error}</p>}
    <div className="dialog-actions"><button className="button secondary" disabled={busy} onClick={onClose}>稍后处理</button><button className="button primary" disabled={busy || !keys.some(key => !saved.includes(key))} onClick={save}>{busy ? '正在保存…' : keys.some(key => !saved.includes(key)) ? '确认学习' : '已完成学习'}</button></div>
  </dialog>;
}

export function LearningNotice({ learning, run, busy, navigate }) {
  const [later, setLater] = useState([]);
  const review = (learning?.reviews || []).find(row => row.status === 'ready' && !later.includes(row.id));
  if (!review) return null;
  return <ReplyReview key={review.id} review={review} run={run} busy={busy} onClose={() => setLater(old => [...old, review.id])} onSaved={() => navigate('replied')}/>;
}

export function AssistantPage({ api, run, busy, active }) {
  const [text, setText] = useState('');
  const [messages, setMessages] = useState([]);
  const [conversation, setConversation] = useState('');
  const [connection, setConnection] = useState(null);
  const [showConnection, setShowConnection] = useState(false);
  const end = useRef(null);
  useEffect(() => { if (active) api('resource?name=assistant').then(setConnection).catch(() => {}); }, [active, api]);
  useEffect(() => {
    // Some WebView versions return a promise. Effects may only return a cleanup function.
    end.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [messages]);
  async function send(event) {
    event.preventDefault();
    const content = text.trim();
    if (!content || busy) return;
    setMessages(old => [...old, { role: 'user', text: content }]);
    setText('');
    const result = await run('page.assistant.chat', { text: content, conversation });
    if (result) {
      setConversation(result.conversation);
      setMessages(old => [...old, { role: 'assistant', text: result.reply, changes: result.changes }]);
    } else {
      setMessages(old => [...old, { role: 'error', text: '本次请求未完成，可以重新发送。' }]);
      setText(content);
    }
  }
  async function apply(change, cancel = false, undo = false) {
    const result = await run(undo ? 'page.assistant.undo' : cancel ? 'page.assistant.cancel' : 'page.assistant.apply', { id: change.id });
    if (result) setMessages(old => old.map(message => ({
      ...message, changes: message.changes?.map(row => row.id === change.id ? {
        ...row, status: undo ? 'undone' : cancel ? 'cancelled' : 'applied', receipt: result.message,
        undoable: result.undoable ?? row.undoable,
      } : row),
    })));
  }
  return <div className="assistant-page">
    <div className="page-header"><div><h1>AI 助手</h1><p>查询设置、调整话术、维护资料，修改前先查看预览。</p></div><button className="button secondary" onClick={() => setShowConnection(!showConnection)}><ArrowSquareOut size={17}/>外部 AI 接入</button></div>
    {showConnection && <section className="assistant-connection"><h2>MCP 连接配置</h2><p>保持软件运行，在支持 MCP 的 AI 工具中添加以下配置。</p><pre className="prose">{JSON.stringify({ mcpServers: { wecom: connection?.mcp } }, null, 2)}</pre></section>}
    <div className="assistant-messages" aria-live="polite">
      {!messages.length && <div className="assistant-empty"><Robot size={32}/><h2>想调整哪一部分？</h2><div className="assistant-examples">{['查看当前模型和学习开关', '把欢迎语改得简短自然一些', '查一下天仙月礼包码怎么兑换'].map(example => <button key={example} className="button secondary" onClick={() => setText(example)}>{example}</button>)}</div></div>}
      {messages.map((message, i) => <article className={'assistant-message ' + message.role} key={i}><strong>{message.role === 'user' ? '你' : 'AI 助手'}</strong><p>{message.text}</p>{message.changes?.map(change => <section className="assistant-change" key={change.id}><h3>变更预览 · {change.action}</h3><div className="change-columns"><div><h4>当前内容</h4><pre className="prose">{typeof change.before === 'string' ? change.before : JSON.stringify(change.before, null, 2)}</pre></div><div><h4>修改后</h4><pre className="prose">{JSON.stringify(change.after, null, 2)}</pre></div></div>{change.status === 'pending' ? <div className="row-actions"><button className="button secondary" disabled={busy} onClick={() => apply(change, true)}>取消</button><button className="button primary" disabled={busy} onClick={() => apply(change)}>应用变更</button></div> : <p className="muted"><CheckCircle size={16}/> {change.status === 'applied' ? change.receipt || '已应用' : change.status === 'undone' ? '已撤销' : '已取消'}</p>}{change.status === 'applied' && change.undoable && <button className="button secondary" disabled={busy} onClick={() => apply(change, false, true)}>撤销这次变更</button>}</section>)}</article>)}
      {busy && <p className="muted" role="status">正在处理，请稍候…</p>}
      <div ref={end}/>
    </div>
    <form className="assistant-composer" onSubmit={send}><label className="sr-only" htmlFor="assistant-input">给 AI 助手的指令</label><textarea id="assistant-input" value={text} maxLength={6000} disabled={busy} placeholder="输入你想查询或修改的内容…" onChange={e => setText(e.target.value)} onKeyDown={event => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter' && !event.nativeEvent.isComposing) send(event); }}/><div><span className="muted">Ctrl + Enter 发送</span><button className="button primary" disabled={busy || !text.trim()}><PaperPlaneTilt size={18}/>发送</button></div></form>
  </div>;
}
