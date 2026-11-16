import { useEffect, useRef, useState } from 'react';
import { FeedbackContext, PageRouter } from './Pages';
import './pages.css';
import { ChatsCircle, Tray, CheckCircle, BookOpen, ChartBar, GearSix, MagnifyingGlass,
  CaretDown, ArrowSquareOut, ArrowLeft, X, PaperPlaneTilt, PencilSimple, ArrowCounterClockwise,
  Pause, Play, Robot, Info, WarningCircle, Clock, Hash, Prohibit, CaretRight, Check } from '@phosphor-icons/react';

const statusNames = { pending: '待人工确认', queued: '等待发送', failed: '发送失败', unknown: '结果待核实' };
const guardNames = { low_risk: '低风险', high_risk: '需要人工判断', human: '人工确认', hold: '需要人工确认' };
const timeLabel = value => new Date(value * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
const dateLabel = value => new Date(value * 1000).toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' });
let token = new URLSearchParams(location.hash.slice(1)).get('session') || sessionStorage.getItem('workbenchSession') || '';
if (token) sessionStorage.setItem('workbenchSession', token);
if (location.hash) history.replaceState(null, '', location.pathname);

async function api(path, options = {}) {
  // A desktop relaunch may reuse an existing tab with a new fragment credential.
  const incoming = new URLSearchParams(location.hash.slice(1)).get('session');
  if (incoming) {
    token = incoming;
    sessionStorage.setItem('workbenchSession', token);
    history.replaceState(null, '', location.pathname);
  }
  const response = await fetch('/api/' + path, { ...options, headers: { Authorization: 'Bearer ' + token,
    'Content-Type': 'application/json', ...options.headers } });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || '连接失败，请重试');
  return body;
}

function Avatar({ name, bot = false, small = false }) {
  return <span className={'avatar' + (bot ? ' bot' : '') + (small ? ' small' : '')} aria-hidden="true">
    {bot ? <Robot size={22} /> : (name || '客').replace(/[@（(].*/, '').slice(0, 1)}
  </span>;
}

function IconButton({ icon: Icon, label, ...props }) {
  return <button className="icon-button" type="button" title={label} aria-label={label} {...props}><Icon size={20} /></button>;
}

export function App() {
  const [page, setPage] = useState('pending');
  const [state, setState] = useState(null);
  const [connected, setConnected] = useState(false);
  const [connectionError, setConnectionError] = useState('');
  const [selectedKey, setSelectedKey] = useState(null);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [drafts, setDrafts] = useState({});
  const [editing, setEditing] = useState({});
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(null);
  const pendingRequest = useRef(null);
  const ending = useRef(null);
  const [details, setDetails] = useState(true);
  const [mobileDetail, setMobileDetail] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [confirmIgnore, setConfirmIgnore] = useState(null);
  const searchRef = useRef(null);
  const editor = useRef(null);
  const modal = useRef(null);
  const rows = state?.items || [];
  const selected = rows.find(row => row.key === selectedKey) || null;
  const attention = rows.filter(row => ['failed', 'unknown'].includes(row.send_status)).length;
  const visible = rows.filter(row => (filter !== 'attention' || ['failed', 'unknown'].includes(row.send_status)) &&
    (row.customer_name + ' ' + row.customer_message).toLowerCase().includes(query.trim().toLowerCase()));
  const savedDraft = selected && drafts[selected.key];
  const draft = savedDraft?.text ?? selected?.ai_reply ?? '';
  const staleDraft = Boolean(savedDraft && selected && savedDraft.revision !== selected.revision);
  const isEditing = selected && (editing[selected.key] || !selected.ai_reply);
  const locked = !connected || Boolean(busy) || selected?.send_status === 'queued';

  useEffect(() => {
    let alive = true, timer;
    const controller = new AbortController();
    async function poll() {
      try {
        const next = await api('state', { signal: controller.signal });
        if (!alive) return;
        setState(next); setConnected(next.connected !== false); setConnectionError('');
        const pending = pendingRequest.current;
        if (pending) {
          const result = next.operations?.[pending.id];
          if (result && result.status !== 'pending') {
            let output = {};
            if (result.status === 'done' && pending.action.startsWith('page.')) {
              const receipt = await api('result?id=' + encodeURIComponent(pending.id));
              output = receipt.result || {};
            }
            setToast({ text: result.message, error: result.status === 'error' });
            if (result.status === 'error' && ['exit', 'restart'].includes(pending.action)) ending.current = null;
            setBusy(null); pendingRequest.current = null;
            pending.resolve?.(result.status === 'done' ? { ...output, message: result.message } : null);
            if (result.status === 'done' && pending.key) {
              setDrafts(old => { const updated = { ...old }; delete updated[pending.key]; return updated; });
            }
          } else if (!result && Date.now() - pending.started > 15000) {
            setToast({ text: '服务未收到此操作，请确认队列状态后重试。', error: true });
            pendingRequest.current = null; setBusy(null);
            pending.resolve?.(null);
          }
        }
      } catch (error) {
        if (!alive) return;
        setConnected(false);
        if (ending.current) {
          const message = ending.current === 'restart' ? '重启请求已提交，当前连接已关闭。请等待新工作区打开。' : '退出请求已提交，程序连接已关闭。可以关闭此页面。';
          setConnectionError(message);
          setToast({ text: message, error: false });
          const pending = pendingRequest.current;
          pendingRequest.current = null; setBusy(null);
          pending?.resolve?.({ message });
          alive = false; // A restarted desktop opens a fresh authenticated URL.
        } else {
          setConnectionError(error.message.includes('会话') ? error.message : '与桌面程序的连接已断开。请保持桌面程序运行，连接恢复后可继续处理。');
        }
      }
      if (alive) timer = setTimeout(poll, 800);
    }
    poll();
    return () => { alive = false; controller.abort(); clearTimeout(timer); };
  }, []);

  useEffect(() => {
    if (!visible.some(row => row.key === selectedKey)) {
      setSelectedKey(visible[0]?.key || null);
      if (!visible.length) setMobileDetail(false);
    }
  }, [rows, selectedKey, query, filter]);

  useEffect(() => {
    const shortcut = event => {
      if (event.key === 'Escape') setNavOpen(false);
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault(); setMobileDetail(false); searchRef.current?.focus();
      }
    };
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  }, []);
  useEffect(() => {
    if (!toast || toast.error) return;
    const timer = setTimeout(() => setToast(null), 5000);
    return () => clearTimeout(timer);
  }, [toast]);
  useEffect(() => { if (isEditing) editor.current?.focus(); }, [isEditing, selectedKey]);
  useEffect(() => {
    if (confirmIgnore) modal.current?.showModal();
    else modal.current?.close();
  }, [confirmIgnore]);

  async function command(action, extra = {}) {
    if (!connected || pendingRequest.current) return;
    const requestId = crypto.randomUUID();
    let resolve;
    const completion = new Promise(done => { resolve = done; });
    pendingRequest.current = { id: requestId, key: extra.key, action, started: Date.now(), resolve };
    setBusy(action); setToast(null);
    try {
      await api('command', { method: 'POST', body: JSON.stringify({ action, requestId, ...extra }) });
      if (['exit', 'restart'].includes(action)) ending.current = action;
    } catch (error) {
      // Keep waiting for the operation receipt. A failed HTTP response is not proof
      // that the command failed, so never automatically repeat a send.
      setToast({ text: error.message + '；正在核对操作结果，请勿重复发送。', error: true });
    }
    return completion;
  }
  function send() {
    if (!selected || locked || !draft.trim() || staleDraft) return;
    command(draft === selected.ai_reply ? 'send' : 'edit', {
      key: selected.key, revision: selected.revision, text: draft,
    });
  }
  function resetDraft() {
    setDrafts(old => { const next = { ...old }; delete next[selected.key]; return next; });
    setEditing(old => ({ ...old, [selected.key]: false }));
  }
  function choose(row) { setSelectedKey(row.key); setMobileDetail(true); }
  useEffect(() => { document.title = ({pending:'待人工',all:'全部消息',replied:'已回复',dashboard:'数据看板',knowledge:'资料库',prompts:'提示词',learned:'学到的',probe:'试问一句',settings:'设置'})[page] + ' · 企业微信智能客服'; }, [page]);
  function navigate(target) { setNavOpen(false); setPage(target); }
  function native(target) { navigate(({ '全部': 'all', '已回复': 'replied', '数据': 'dashboard', '知识库': 'knowledge', '设置': 'settings' })[target]); }

  return <FeedbackContext.Provider value={toast}><div className={'app' + (mobileDetail ? ' show-conversation' : '') + (navOpen ? ' nav-open' : '')}>
    <header className="titlebar"><ChatsCircle size={16} weight="fill"/><span>企业微信智能客服</span>
      {state?.demo && <span className="demo-label">设计预览 · 演示数据</span>}
      <span className={'connection' + (connected ? ' connected' : '')}><i />{connected ? '本机已连接' : state ? '连接中断' : '正在连接'}</span>
    </header>

    <nav className="rail" aria-label="应用导航">
      <button className={'app-icon' + (['pending','all','replied'].includes(page) ? ' current' : '')} aria-label="工作台导航" title="工作台导航" onClick={() => { setPage('pending'); setFilter('all'); setMobileDetail(false); setNavOpen(!navOpen); }}><ChatsCircle size={28} weight="fill"/></button>
      <div className="rail-divider" />
      <button className={'app-icon' + (['knowledge','prompts','learned','probe'].includes(page) ? ' current' : '')} title="知识库" aria-label="打开知识库" onClick={() => native('知识库')}><BookOpen size={24}/></button>
      <button className={'app-icon' + (page === 'dashboard' ? ' current' : '')} title="数据看板" aria-label="打开数据看板" onClick={() => native('数据')}><ChartBar size={24}/></button>
      <div className="rail-spacer" />
      <button className={'app-icon settings' + (page === 'settings' ? ' current' : '')} title="设置" aria-label="打开设置" onClick={() => native('设置')}><GearSix size={24}/></button>
    </nav>

    {navOpen && <button className="nav-scrim" aria-label="收起工作区导航" onClick={() => setNavOpen(false)}/>}
    <aside className="workspace">
      <div className="workspace-heading"><strong>客服工作区</strong><span className="workspace-tag">本地</span></div>
      <div className="workspace-body">
        <div className="nav-label"><CaretDown size={14}/>工作台</div>
        <button className={'channel' + (page === 'pending' && filter === 'all' ? ' active' : '')} onClick={() => { navigate('pending'); setFilter('all'); setMobileDetail(false); }}><Tray size={20}/><span>待人工</span><b>{rows.length}</b></button>
        <button className={'channel' + (page === 'all' ? ' active' : '')} onClick={() => native('全部')}><Hash size={20}/><span>全部消息</span></button>
        <button className={'channel' + (page === 'replied' ? ' active' : '')} onClick={() => native('已回复')}><CheckCircle size={20}/><span>已回复</span></button>
        <div className="nav-label attention-label"><CaretDown size={14}/>处理状态</div>
        <button className={'channel' + (page === 'pending' && filter === 'attention' ? ' active' : '')} onClick={() => { navigate('pending'); setFilter('attention'); setMobileDetail(false); }}><WarningCircle size={20}/><span>需要关注</span>{attention > 0 && <b className="attention-count">{attention}</b>}</button>
        <p className="nav-hint">发送失败和结果待核实的消息<br/>会显示在这里</p>
        <div className="nav-label attention-label"><CaretDown size={14}/>管理</div>
        {[['dashboard','数据看板',ChartBar],['knowledge','资料库',BookOpen],['prompts','提示词',PencilSimple],['learned','学到的',Robot],['probe','试问一句',ChatsCircle],['settings','设置',GearSix]].map(([id,label,Icon]) => <button key={id} className={'channel'+(page===id?' active':'')} onClick={()=>navigate(id)}><Icon size={20}/><span>{label}</span></button>)}
        <div className="workspace-note"><BookOpen size={18}/><p>回复前，先确认客户的问题<br/><button onClick={() => native('知识库')} disabled={!connected || !!busy}>查阅知识库 <ArrowSquareOut size={12}/></button></p></div>
      </div>
      <div className="service-panel"><Avatar bot small/><div><strong>自动回复</strong><span><i className={state?.paused ? 'status-dot paused' : 'status-dot'}/>{state?.paused ? '未运行' : '运行中'}</span></div>
        <IconButton icon={state?.paused ? Play : Pause} label={state?.paused ? '启动自动回复' : '停止自动回复'} onClick={() => command('service')} disabled={!connected || !!busy}/>
      </div>
    </aside>

    {page === 'pending' ? <><section className="inbox" aria-label="待处理消息">
      <header className="panel-heading"><h1>{filter === 'attention' ? '需要关注' : '待人工'}</h1><span>{visible.length}</span></header>
      <div className="queue-tools"><label className="search"><MagnifyingGlass size={17}/><input ref={searchRef} aria-label="搜索客户或消息" placeholder="搜索客户或消息" value={query} onChange={e => setQuery(e.target.value)}/>{query ? <IconButton icon={X} label="清空搜索" onClick={() => setQuery('')}/> : <kbd>Ctrl K</kbd>}</label>
        <div className="queue-caption"><span>{query ? '搜索结果' : '最近收到'}</span><span>按消息处理</span></div>
      </div>
      <div className="queue-list">
        {visible.map(row => <button key={row.key} className={'queue-item' + (row.key === selectedKey ? ' selected' : '')} aria-pressed={row.key === selectedKey} onClick={() => choose(row)}>
          <Avatar name={row.customer_name}/><div className="queue-copy"><div className="queue-name"><strong>{row.customer_name}</strong><time>{timeLabel(row.timestamp)}</time></div><p>{row.customer_message}</p><span className={'row-status ' + row.send_status}>{row.send_status === 'failed' || row.send_status === 'unknown' ? <WarningCircle size={12}/> : <span className="tiny-dot"/>}{statusNames[row.send_status] || '待人工确认'}{drafts[row.key] && <em>· 已编辑</em>}</span></div>
        </button>)}
        {!visible.length && <div className="queue-empty"><Tray size={32}/><strong>{query ? '没有匹配的消息' : filter === 'attention' ? '暂无异常消息' : '待处理队列已清空'}</strong><p>{query ? '试试客户名或消息中的关键词' : '新消息需要人工确认时会显示在这里'}</p>{query && <button className="text-button" onClick={() => setQuery('')}>清空搜索</button>}</div>}
      </div>
      <footer className="queue-footer"><span className="status-dot"/>{new Set(rows.map(row => row.customer_name)).size} 位客户 · {rows.length} 条待处理</footer>
    </section>

    <main className="conversation">
      <header className="conversation-heading"><button className="icon-button back" onClick={() => setMobileDetail(false)} aria-label="返回消息列表"><ArrowLeft size={20}/></button>
        {selected ? <><Avatar name={selected.customer_name} small/><div className="customer-heading"><strong>{selected.customer_name}</strong><span>待人工消息</span></div><div className="heading-actions"><span className={'status-label ' + selected.send_status}>{statusNames[selected.send_status]}</span><IconButton icon={Info} label={details ? '收起消息信息' : '查看消息信息'} aria-pressed={details} onClick={() => setDetails(!details)}/></div></> : <><Tray size={22}/><strong>消息处理</strong></>}
      </header>
      {connectionError && <div className="notice error" role="alert"><WarningCircle size={18}/><span>{connectionError}</span></div>}
      {state?.banner?.text && <div className={'notice ' + state.banner.level}><Info size={18}/><span>{state.banner.text}</span></div>}
      {state?.demo && <div className="preview-note">演示模式，操作仅作用于示例消息，不会发送给客户</div>}
      {selected ? <>
        <div className="compact-info"><span>资料匹配度 {Math.round(selected.confidence * 100)}%</span><span>{guardNames[selected.guard_decision] || selected.guard_decision || '待人工确认'}</span></div>
        <div className="conversation-body" key={selected.key}>
          <section className="thread" aria-label="客户消息">
            <div className="thread-intro"><Avatar name={selected.customer_name}/><h2>{selected.customer_name}</h2><p>查看客户原话，确认回复后再发送</p></div>
            <div className="date-divider"><span>{dateLabel(selected.timestamp)}</span></div>
            <article className="message"><Avatar name={selected.customer_name}/><div><div className="message-heading"><strong>{selected.customer_name}</strong><time>{timeLabel(selected.timestamp)}</time><span>客户</span></div><p>{selected.customer_message}</p></div></article>
            <div className="handoff"><span className="handoff-line"/><Robot size={16}/><span>已转入待人工，等待确认回复</span></div>
          </section>
          {details && <aside className="context" aria-label="消息信息"><h3>消息信息</h3><dl><dt>处理状态</dt><dd className={selected.send_status}>{statusNames[selected.send_status]}</dd><dt>收到时间</dt><dd>{dateLabel(selected.timestamp)} {timeLabel(selected.timestamp)}</dd><dt>资料匹配度</dt><dd className="score">{Math.round(selected.confidence * 100)}<span>%</span></dd></dl><p className="context-explanation">表示资料与问题的匹配程度，<br/>不代表回复的准确率</p><div className="context-divider"/><h3>判断结果</h3><p className="guard-value">{guardNames[selected.guard_decision] || selected.guard_decision || '等待人工确认'}</p><p className="context-explanation">请结合客户原话检查回复内容</p></aside>}
        </div>
        <div className="composer-zone">
          {selected.send_error && <div className={'delivery-warning ' + selected.send_status}><WarningCircle size={18}/><span>{selected.send_error}{selected.send_status === 'unknown' && !state.demo && ' 继续发送时，桌面窗口会要求确认。'}</span></div>}
          {staleDraft && <div className="delivery-warning" role="alert"><WarningCircle size={18}/><span>消息已更新，保留了你的编辑内容。请先核对最新草稿。</span><button className="text-button" onClick={resetDraft}>载入最新草稿</button></div>}
          <section className={'composer' + (isEditing ? ' editing' : '')} aria-label="回复草稿">
            <div className="composer-heading"><Robot size={20}/><strong>{isEditing ? '编辑回复' : 'AI 回复草稿'}</strong><span className="draft-label">尚未发送</span><div className="composer-tools">{isEditing ? <IconButton icon={ArrowCounterClockwise} label="恢复原始草稿" onClick={resetDraft} disabled={locked}/> : <button className="text-button" onClick={() => setEditing(old => ({ ...old, [selected.key]: true }))} disabled={locked}><PencilSimple size={16}/>编辑回复</button>}</div></div>
            {isEditing ? <textarea ref={editor} aria-label="回复内容" maxLength={10000} placeholder="输入要回复给客户的内容…" value={draft} disabled={locked}
              onChange={e => setDrafts(old => ({ ...old, [selected.key]: { text: e.target.value, revision: savedDraft?.revision || selected.revision } }))}
              onKeyDown={e => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }}/>
              : <p className="draft-text">{draft}</p>}
            <div className="composer-bottom"><span>{isEditing ? draft.length.toLocaleString() + ' / 10,000' : '请确认信息无误后发送'}</span>{isEditing && <span><kbd>Ctrl</kbd> + <kbd>Enter</kbd> 发送</span>}</div>
          </section>
          <div className="action-bar"><button className="button quiet" onClick={() => setConfirmIgnore(selected)} disabled={!connected || !!busy}><Prohibit size={17}/>忽略这条</button><span className="send-target">回复给 <strong>{selected.customer_name}</strong></span><button className="button primary" disabled={locked || !draft.trim() || staleDraft} onClick={send}><PaperPlaneTilt size={18} weight="fill"/>{busy === 'send' || busy === 'edit' ? '正在提交…' : selected.send_status === 'queued' ? '等待发送…' : selected.send_status === 'unknown' ? '核实后重试' : selected.send_status === 'failed' ? '重试发送' : '发送回复'}</button></div>
        </div>
      </> : <div className="conversation-empty"><div className="empty-icon"><CheckCircle size={40}/></div><h2>{state ? rows.length ? '没有匹配的待处理消息' : '当前没有待处理消息' : '正在连接工作台'}</h2><p>{state ? rows.length ? '调整搜索或筛选条件，查看其他消息。' : '新消息需要人工确认时，你可以在这里查看和回复。' : '正在从桌面程序读取待人工队列…'}</p></div>}
    </main>
    </> : null}
    <PageRouter page={page} navigate={navigate} api={api} run={command} busy={!!busy || !connected} connected={connected} demo={state?.demo} connectionError={connectionError}/>
    {toast && <div className={'toast' + (toast.error ? ' toast-error' : '')} role="status">{toast.error ? <WarningCircle size={19}/> : <Check size={19}/>}<span>{toast.text}</span><IconButton icon={X} label="关闭提示" onClick={() => setToast(null)}/></div>}
    <dialog ref={modal} aria-labelledby="ignore-title" onCancel={() => setConfirmIgnore(null)} onClose={() => setConfirmIgnore(null)}><h2 id="ignore-title">忽略这条消息？</h2><p>这会把 <strong>{confirmIgnore?.customer_name}</strong> 的这条消息移出待人工队列。{confirmIgnore?.send_status === 'queued' ? '已经开始的发送可能无法撤回。' : '不会发送回复。'}</p><blockquote>{confirmIgnore?.customer_message}</blockquote><div className="dialog-actions"><button className="button secondary" onClick={() => setConfirmIgnore(null)}>取消</button><button className="button danger" onClick={() => { command('ignore', { key: confirmIgnore.key, revision: confirmIgnore.revision }); setConfirmIgnore(null); }}>确认忽略</button></div></dialog>
  </div></FeedbackContext.Provider>;
}
