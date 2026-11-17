import { AssistantPage, ReplyReview } from './Assistant';
import { PageBoundary } from './PageBoundary';
import { createContext, useContext, useEffect, useRef, useState } from 'react';
import { ArrowClockwise, DownloadSimple, Plus, MagnifyingGlass, X, BookOpen, FileText, UploadSimple, PencilSimple, Trash, ArrowCounterClockwise, CaretLeft, CaretRight, WarningCircle, ChartBar, Robot, GearSix, CheckCircle, FloppyDisk, Eye, Play } from '@phosphor-icons/react';
export const FeedbackContext = createContext(null);

const names = {
  assistant: 'AI 助手',
  all: '全部消息',
  replied: '已回复',
  dashboard: '数据看板',
  knowledge: '资料库',
  prompts: '提示词',
  learned: '学到的',
  probe: '试问一句',
  settings: '设置'
};
const labels = {
  auto_send: '自动回复',
  replied: '已回复',
  hold: '转人工占位',
  greeting: '欢迎语',
  escalated: '转人工',
  ignored: '已忽略',
  blocked: '已拦截',
  no_reply: '不回复'
};
const reasonText = value => {
  const s = value || '未记录原因';
  const labels = {hallucinated_number:'回答包含未经资料确认的数字',uncertainty_keyword:'回答存在不确定表述',retrieval_low_confidence:'未找到足够相关的资料',low_confidence:'资料匹配度不足',generic_pattern:'回复缺少实际内容',non_text:'客户发送了图片、语音或文件'};
  return Object.entries(labels).find(([key])=>s.includes(key))?.[1] || s;
};
const outgoing = new Set(['auto_send', 'replied', 'hold', 'greeting']);
const today = () => new Date().toLocaleDateString('sv-SE');
const ago = n => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toLocaleDateString('sv-SE');
};
const csvCell = value => {
  let s = String(value ?? '');
  if (/^[=+@\-]/.test(s)) s = "'" + s;
  return '"' + s.replaceAll('"', '""') + '"';
};
function download(name, headers, rows) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob(['\ufeff' + [headers, ...rows].map(r => r.map(csvCell).join(',')).join('\r\n')], {
    type: 'text/csv;charset=utf-8'
  }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function B({
  children,
  icon: Icon,
  tone = '',
  ...props
}) {
  return <button type="button" className={'button ' + tone} {...props}>{Icon && <Icon size={17} />} {children}</button>;
}
function Empty({
  title = '暂无内容',
  text = '数据准备好后会显示在这里'
}) {
  return <div className="page-empty"><BookOpen size={36} /><h3>{title}</h3><p>{text}</p></div>;
}
function Modal({
  title,
  children,
  onClose,
  wide = false
}) {
  const ref = useRef(null);
  const feedback = useContext(FeedbackContext);
  useEffect(() => {
    const d = ref.current;
    d.showModal();
    return () => d.close();
  }, []);
  return <dialog className={'page-dialog' + (wide ? ' wide' : '')} ref={ref} onCancel={onClose}><div className="dialog-heading"><h2>{title}</h2><B icon={X} aria-label="关闭弹窗" onClick={onClose} /></div>{feedback?.error && <div role="alert" className="inline-note error">{feedback.text}</div>}{children}</dialog>;
}
function Confirm({
  title,
  children,
  onClose,
  onConfirm,
  busy,
  danger = false
}) {
  return <Modal title={title} onClose={onClose}><div className="dialog-copy">{children}</div><div className="dialog-actions"><B tone="secondary" onClick={onClose}>取消</B><B tone={danger ? 'danger' : 'primary'} disabled={busy} onClick={onConfirm}>{busy ? '正在处理…' : '确认'}</B></div></Modal>;
}
function Search({
  value,
  onChange,
  placeholder = '搜索',
  label = placeholder
}) {
  return <label className="page-search"><MagnifyingGlass size={18} /><input aria-label={label} placeholder={placeholder} value={value} onChange={e => onChange(e.target.value)} />{value && <button aria-label="清空搜索" onClick={() => onChange('')}><X size={15} /></button>}</label>;
}
function useResource(api, name, params = {}, active = true) {
  const [data, setData] = useState(null),
    [error, setError] = useState(''),
    [loading, setLoading] = useState(false),
    [version, setVersion] = useState(0);
  const key = JSON.stringify(params);
  useEffect(() => {
    if (!active) return;
    let alive = true;
    setLoading(true);
    setError('');
    api('resource?' + new URLSearchParams({
      name,
      ...JSON.parse(key)
    })).then(next => {
      if (alive) setData(next);
    }).catch(e => {
      if (alive) setError(e.message);
    }).finally(() => {
      if (alive) setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, [api, name, key, version, active]);
  return {
    data,
    error,
    loading,
    refresh: () => setVersion(v => v + 1)
  };
}
function LoadState({
  resource,
  children
}) {
  if (resource.error) return <div className="page-error" role="alert"><WarningCircle size={22} /><span>{resource.error}</span><B onClick={resource.refresh}>重试</B></div>;
  if (!resource.data) return <div className="page-loading">正在读取本机数据…</div>;
  return children(resource.data);
}
function Header({
  title,
  description,
  children
}) {
  return <div className="page-header"><div><h1>{title}</h1><p>{description}</p></div><div className="header-tools">{children}</div></div>;
}
function Pagination({
  page,
  total,
  size = 50,
  onPage
}) {
  return <div className="pagination"><span>共 {total} 条 · 第 {page + 1} / {Math.max(1, Math.ceil(total / size))} 页</span><B icon={CaretLeft} aria-label="上一页" disabled={page === 0} onClick={() => onPage(page - 1)} /><B icon={CaretRight} aria-label="下一页" disabled={(page + 1) * size >= total} onClick={() => onPage(page + 1)} /></div>;
}
function History({
  navigate,
  page,
  api,
  run,
  busy,
  active
}) {
  const r = useResource(api, 'records', {}, active);
  const [q, setQ] = useState(''),
    [status, setStatus] = useState('all'),
    [index, setIndex] = useState(0),
    [selected, setSelected] = useState(null),
    [clear, setClear] = useState(false),
    [review, setReview] = useState(null),
    [legacyQuestion, setLegacyQuestion] = useState('');
  const rows = (r.data?.rows || []).filter(row => (page !== 'replied' || outgoing.has(row.action)) && (status === 'all' || row.action === status) && [row.customer, row.question, row.message, row.reply].join(' ').includes(q));
  useEffect(() => setIndex(0), [q, status, page]);
  useEffect(() => setLegacyQuestion(''), [selected?.record_id]);
  useEffect(() => { if (!active) return; const timer = setInterval(r.refresh, 3000); return () => clearInterval(timer); }, [active]);
  return <><Header title={names[page]} description={page === 'replied' ? '查看已发送回复、学习状态与入库结果' : '按时间回看消息与处理结果，查看完整原话和回复'}><B icon={ArrowClockwise} onClick={r.refresh}>刷新</B><B icon={DownloadSimple} disabled={!rows.length} onClick={() => download(names[page] + '.csv', ['时间', '客户', '客户消息', '处理结果', '回复内容'], rows.map(x => [x.timestamp, x.customer, x.message, labels[x.action] || x.action, x.reply]))}>导出 CSV</B><B tone="quiet" onClick={() => setClear(true)}>清空列表</B></Header><div className="page-toolbar"><Search value={q} onChange={setQ} placeholder="搜索客户、原话或回复" /><select aria-label="处理结果筛选" value={status} onChange={e => setStatus(e.target.value)}><option value="all">所有处理结果</option>{Object.entries(labels).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select><span className="toolbar-note">最新消息在前</span></div><LoadState resource={r}>{() => rows.length ? <><div className="table-scroll"><table><thead><tr><th>时间</th><th>客户</th><th>消息内容</th><th>处理结果</th><th>回复</th><th>学习状态</th></tr></thead><tbody>{rows.slice(index * 50, index * 50 + 50).map((row, i) => <tr key={index * 50 + i}><td className="table-time">{row.timestamp}</td><td className="table-customer">{row.customer}</td><td><button className="cell-link" onClick={() => setSelected(row)}>{row.question || row.message || '—'}</button></td><td><span className={'table-tag ' + (outgoing.has(row.action) ? 'positive' : '')}>{labels[row.action] || row.action}</span></td><td><button className="cell-link secondary-text" onClick={() => setSelected(row)}>{row.reply || '—'}</button></td><td><button className="cell-link" onClick={() => setSelected(row)}>{row.learning?.label || '尚无学习记录'}</button></td></tr>)}</tbody></table></div><Pagination page={index} total={rows.length} onPage={setIndex} /></> : <Empty title={q ? '没有匹配的记录' : '暂无消息记录'} text="新消息处理后会出现在这里" />}</LoadState>{selected && <Modal title={selected.customer + ' · 消息详情'} wide onClose={() => setSelected(null)}><p className="muted">{selected.timestamp} · {labels[selected.action] || selected.action}</p><h3>客户原话</h3><pre className="prose">{selected.question || (selected.message !== selected.reply ? selected.message : '旧记录未保存客户原话')}</pre><h3>回复内容</h3><pre className="prose">{selected.reply || '暂无回复'}</pre><section className="learning-receipt"><h3>学习状态</h3><p className="muted">当前资料库 · {r.data.archiveName || '当前档案'}</p>{!selected.question && <label className="form-stack">补充这条回复对应的问题<input value={legacyQuestion} onChange={e => setLegacyQuestion(e.target.value)} maxLength={2000} placeholder="请填写完整问题，包含适用的游戏"/></label>}<p>{selected.learning?.label || '尚无学习记录'}</p>{selected.learning?.result?.rules > 0 && <p>语气习惯 {selected.learning.result.rules} 条</p>}{selected.learning?.result?.tones > 0 && <p>口吻样本 {selected.learning.result.tones} 条</p>}<div className="row-actions">{selected.record_id && (!selected.archive || selected.archive === r.data.archive) && <B disabled={busy || selected.learning?.status === 'analyzing' || (!selected.question && !legacyQuestion.trim())} onClick={async () => {
        const result = await run('page.reply.prepare', { archive: r.data.archive, record: selected.record_id, question: selected.question || legacyQuestion });
        if (result?.review) { setSelected(null); setReview(result.review); r.refresh(); }
      }}>{['ready', 'learned'].includes(selected.learning?.status) ? '查看学习内容' : '分析并学习这条回复'}</B>}<B onClick={() => { setSelected(null); navigate('learned'); }}>查看学习记录</B>{selected.learning?.entries?.length > 0 && <B onClick={() => {
        sessionStorage.setItem('knowledgeSearch', selected.question || '');
        setSelected(null); navigate('knowledge');
      }}>查看入库条目</B>}</div></section></Modal>}{review && <ReplyReview review={review} run={run} busy={busy} onClose={() => setReview(null)} onSaved={r.refresh}/>}{clear && <Confirm title="清空当前消息列表？" danger busy={busy} onClose={() => setClear(false)} onConfirm={async () => {
      if (await run('records.clear')) {
        setClear(false);
        r.refresh();
      }
    }}>清空当前窗口中的记录与本次计数。磁盘上的历史日志仍保留，重启后可重新读取。</Confirm>}</>;
}
function Chart({
  buckets
}) {
  const max = Math.max(1, ...buckets.map(b => b.replies));
  const width = 720,
    height = 200,
    left = 40,
    base = 166,
    plot = 650;
  const series = field => buckets.map((b, i) => `${left + (buckets.length === 1 ? plot / 2 : i * plot / (buckets.length - 1))},${base - b[field] / max * 140}`).join(' ');
  return <svg className="trend-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="所选时间范围内的接待与自动回复趋势">{[0, .5, 1].map(v => <g key={v}><line x1={left} y1={base - v * 140} x2="704" y2={base - v * 140} /><text x="28" y={base - v * 140 + 4} textAnchor="end">{Math.round(v * max)}</text></g>)}{buckets.length > 1 ? <><polyline points={series('replies')} className="replies-line" /><polyline points={series('auto')} className="auto-line" /></> : <circle cx="365" cy={base - (buckets[0]?.replies || 0) / max * 140} r="4" fill="#939cff" />}{buckets.filter((_, i) => i % Math.max(1, Math.ceil(buckets.length / 7)) === 0 || i === buckets.length - 1).map(b => {
      const i = buckets.indexOf(b);
      return <text key={b.label} x={left + (buckets.length === 1 ? plot / 2 : i * plot / (buckets.length - 1))} y="194" textAnchor="middle">{b.label}</text>;
    })}</svg>;
}
function Dashboard({
  api,
  run,
  busy,
  active
}) {
  const [range, setRange] = useState('today'),
    [start, setStart] = useState(today()),
    [end, setEnd] = useState(today()),
    [example, setExample] = useState(false),
    [sample, setSample] = useState(null),
    [entry, setEntry] = useState(null);
  const r = useResource(api, 'dashboard', {
    start,
    end,
    example: example ? '1' : '0'
  }, active);
  const arch = useResource(api, 'probe', {}, active);
  return <><Header title="数据看板" description="查看接待表现，找到最需要补充的资料"><B icon={ArrowClockwise} onClick={r.refresh}>刷新</B><B icon={DownloadSimple} disabled={!r.data?.export_rows?.length} onClick={() => download('客服数据_' + start + '_' + end + '.csv', ['时间', '客户', '客户原话', '处理结果', '归类', '回复'], r.data.export_rows.map(x => [x.ts, x.customer, x.message, x.source, x.path, x.reply]))}>导出 CSV</B></Header><div className="page-toolbar"><div className="segments">{[['today', '今日'], ['week', '近 7 天'], ['custom', '自定义']].map(([key, label]) => <B key={key} tone={range === key ? 'selected' : ''} onClick={() => {
          setRange(key);
          if (key !== 'custom') {
            setEnd(today());
            setStart(key === 'week' ? ago(6) : today());
          }
        }}>{label}</B>)}</div>{range === 'custom' && <div className="date-inputs"><input aria-label="开始日期" type="date" value={start} onChange={e => setStart(e.target.value)} /><span>至</span><input aria-label="结束日期" type="date" value={end} onChange={e => setEnd(e.target.value)} /></div>}<label className="check-label toolbar-end"><input type="checkbox" checked={example} onChange={e => setExample(e.target.checked)} />查看示例数据</label></div>{example && <div className="inline-note">示例模式 · 以下指标不代表真实接待数据</div>}<LoadState resource={r}>{d => <><div className="kpi-row">{[['接待回复', d.replies, '条', `${d.customers} 位客户`], ['自动解决率', d.solve_rate == null ? '—' : Math.round(d.solve_rate * 100), '%', `真答 ${d.auto} · 转人工 ${d.hold}`], ['待人工', d.pending_now, '条', '当前实时积压'], ['中位响应', d.median_reply_seconds == null ? '—' : Number(d.median_reply_seconds).toFixed(1), '秒', '包含占位语']].map(([label, value, unit, note]) => <div className="kpi" key={label}><span>{label}</span><strong>{value}<small>{value !== '—' && unit}</small></strong><p>{note}</p></div>)}</div><div className="metric-detail"><span>人工发出 {d.human || 0} 条</span><span>欢迎语 {d.greeting || 0} 条</span><span>不回复 {d.no_reply || 0} 条</span><span>人工真答中位响应 {d.median_human_seconds == null ? "—" : Number(d.median_human_seconds).toFixed(1)+" 秒"}</span><span>接待 = 自动回复 + 转人工占位语</span></div><section className="data-panel"><div className="section-heading"><div><h2>接待趋势</h2><p>{d.start || start} 至 {d.end || end}</p></div><div className="chart-legend"><span><i />接待</span><span><i />自动回复</span></div></div><Chart buckets={d.buckets || []} />{!d.replies && <p className="empty-caption">所选范围暂无接待记录</p>}</section><div className="dashboard-columns"><section className="data-panel"><div className="section-heading"><h2>消息如何处理</h2><span>点击查看原话样例</span></div>{Object.entries(d.by_path || {}).sort((a, b) => b[1] - a[1]).map(([name, count]) => <button key={name} className="distribution" onClick={() => setSample({
              name,
              content: d.sample_messages?.[name]
            })}><span>{name}</span><span className="bar-track"><i style={{
                  width: count / Math.max(1, ...Object.values(d.by_path)) * 100 + '%'
                }} /></span><b>{count}</b></button>)}{!Object.keys(d.by_path || {}).length && <Empty title="暂无分类记录" />}</section><section className="data-panel"><div className="section-heading"><div><h2>优先补充的资料</h2><p>最常转人工的问题</p></div></div>{(d.unanswered_top || []).map((row, i) => <div className="unanswered-row" key={i}><span className="rank">{i + 1}</span><div><strong>{row.question}</strong><p>{reasonText(row.reason)} · {row.count} 次</p></div><B icon={Plus} aria-label={'补充资料：' + row.question} disabled={example || busy || !arch.data} onClick={() => setEntry({
                question: row.question,
                answer: '',
                unanswered: row.question
              })} /></div>)}{!d.unanswered_top?.length && <Empty title="暂无待补充问题" text="经常转人工的问题会出现在这里" />}</section></div></>}</LoadState>{sample && <Modal title={sample.name + ' · 原话样例'} onClose={() => setSample(null)}><pre className="prose">{Array.isArray(sample.content) ? sample.content.join('\n\n') : sample.content || '暂无样例'}</pre></Modal>}{entry && <EntryEditor entry={entry} archive={arch.data.archive} run={run} busy={busy} onClose={() => setEntry(null)} onSaved={() => {
      setEntry(null);
      r.refresh();
    }} />}</>;
}
function ArchiveBar({
  data,
  run,
  busy,
  refresh
}) {
  const [manage, setManage] = useState(false),
    [action, setAction] = useState('create'),
    [name, setName] = useState(''),
    [target, setTarget] = useState('');
  if (!data) return null;
  return <><div className="archive-bar"><BookOpen size={18} /><label>当前资料库<select aria-label="当前资料库" value={data.archive} disabled={busy} onChange={async e => {
          if (await run('page.archive.switch', {
            archive: data.archive,
            id: e.target.value
          })) refresh();
        }}>{data.archives.map(a => <option value={a.id} key={a.id}>{a.name}</option>)}</select></label><B tone="quiet" onClick={() => {
        setManage(true);
        setTarget(data.archive);
      }}>管理档案</B><span>资料、提示词与学习记录随档案切换</span></div>{manage && <Modal title="管理资料库档案" onClose={() => setManage(false)}><div className="form-stack"><label>操作<select value={action} onChange={e => setAction(e.target.value)}><option value="create">新建空资料库</option><option value="copy">复制当前资料库</option><option value="rename">重命名档案</option><option value="delete">删除档案</option></select></label>{['rename', 'delete'].includes(action) && <label>目标档案<select value={target} onChange={e => setTarget(e.target.value)}>{data.archives.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>}{action !== 'delete' && <label>档案名称<input value={name} maxLength={80} onChange={e => setName(e.target.value)} placeholder="例如：游戏账号售后" /></label>}<p className="muted">{action === 'create' ? '新档案为空资料库，沿用当前档案的提示词与学习语气。' : action === 'copy' ? '复制资料条目、上传源文件、提示词与学习记录。' : action === 'delete' ? '将删除资料索引，源文件与提示词移至回收目录。不能删除默认或当前正在使用的档案。' : '修改档案显示名称，保留已有资料。'}</p></div><div className="dialog-actions"><B onClick={() => setManage(false)}>取消</B><B tone={action === 'delete' ? 'danger' : 'primary'} disabled={busy || action !== 'delete' && !name.trim()} onClick={async () => {
          if (await run('page.archive.' + action, {
            archive: data.archive,
            id: target,
            name
          })) {
            setManage(false);
            setName('');
            refresh();
          }
        }}>{busy ? '处理中…' : '确认' + {
            create: '新建',
            copy: '复制',
            rename: '重命名',
            delete: '删除'
          }[action]}</B></div></Modal>}</>;
}
function EntryEditor({
  entry,
  archive,
  run,
  busy,
  onClose,
  onSaved
}) {
  const [question, setQuestion] = useState(entry.question || ''),
    [answer, setAnswer] = useState(entry.id && !entry.faq ? entry.text : entry.answer || '');
  return <Modal wide title={entry.id ? '编辑资料' : '新增资料'} onClose={onClose}><form onSubmit={async e => {
      e.preventDefault();
      if (await run(entry.id ? 'page.kb.edit' : 'page.kb.add', {
        archive,
        id: entry.id,
        revision: entry.revision,
        question,
        answer,
        unanswered: entry.unanswered
      })) onSaved();
    }}><div className="form-stack">{(!entry.id || entry.faq) && <label>客户问题<textarea rows={2} value={question} onChange={e => setQuestion(e.target.value)} placeholder="客户会怎么问？" /></label>}<label>{entry.id && !entry.faq ? '资料全文' : '销售回答'}<textarea required rows={7} value={answer} onChange={e => setAnswer(e.target.value)} placeholder="填写准确的业务资料" /></label><p className="muted">保存后会重新生成索引并立即生效。价格、型号与政策请按原始资料核对。</p></div><div className="dialog-actions"><B onClick={onClose}>取消</B><B tone="primary" icon={FloppyDisk} type="submit" disabled={busy || !answer.trim()}>{busy ? '正在保存…' : '保存并生效'}</B></div></form></Modal>;
}
async function encodeFiles(files) {
  const list = Array.from(files);
  if (list.reduce((n, f) => n + f.size, 0) > 22 * 1024 * 1024) throw new Error('本次文件总大小不能超过 22 MB，请分批导入。');
  return Promise.all(list.map(file => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve({
      name: file.name,
      data: reader.result.split(',')[1]
    });
    reader.onerror = () => reject(new Error('文件读取失败'));
    reader.readAsDataURL(file);
  })));
}
function Unanswered({api, run, busy, onClose, onSaved}) {
  const r = useResource(api, 'unanswered');
  const [entry, setEntry] = useState(null), [clear, setClear] = useState(false);
  return <><Modal title="常见转人工问题" wide onClose={onClose}><LoadState resource={r}>{d => <>
    <p className="muted">共 {d.rows.length} 个问题 · 累计 {d.total} 次转人工 · {d.todo} 条待补。此统计跨资料库汇总。</p>
    <div className="unanswered-list">{d.rows.map((row, i) => <article className="fact-row" key={row.question}>
      <div><h3>{i+1}. {row.question}</h3><p>{reasonText(row.reason)}</p><small>{row.count} 次 · {row.done_ts ? '已补资料' : '待补'} · 最近 {new Date(row.last_ts*1000).toLocaleString('zh-CN')}</small></div>
      <div className="row-actions"><B disabled={busy || !!row.done_ts} onClick={async () => {if (await run('page.unanswered.done', {archive:d.archive,question:row.question})) r.refresh()}}>标记已补</B><B tone="primary" disabled={busy} onClick={() => setEntry({question:row.question, unanswered:row.question})}>补充资料</B></div>
    </article>)}{!d.rows.length && <Empty title="暂无转人工问题"/>}</div>
    <div className="dialog-actions"><B tone="quiet" disabled={busy || !d.rows.length} onClick={() => setClear(true)}>清空统计</B><B onClick={r.refresh}>刷新</B><B onClick={onClose}>关闭</B></div>
    </>}</LoadState></Modal>{entry && <EntryEditor entry={entry} archive={r.data.archive} run={run} busy={busy} onClose={() => setEntry(null)} onSaved={() => {setEntry(null);r.refresh();onSaved()}}/>}
    {clear && <Confirm title="清空转人工问题统计？" danger busy={busy} onClose={() => setClear(false)} onConfirm={async () => {if (await run('page.unanswered.clear',{archive:r.data.archive})) {setClear(false);r.refresh()}}}>问题排行、次数与已补标记将清空，资料库内容不受影响。</Confirm>}</>;
}

function Knowledge({
  api,
  run,
  busy,
  active
}) {
  const [q, setQ] = useState(''),
    [search, setSearch] = useState(''),
    [page, setPage] = useState(0),
    [entry, setEntry] = useState(null),
    [confirm, setConfirm] = useState(null),
    [ingest, setIngest] = useState(false),
    [imaOpen, setImaOpen] = useState(false),
    [unansweredOpen, setUnansweredOpen] = useState(false),
    [uploadNote, setUploadNote] = useState('');
  const input = useRef(null);
  const r = useResource(api, 'knowledge', {
    query: search,
    page
  }, active);
  useEffect(() => {
    if (!active) return;
    const question = sessionStorage.getItem('knowledgeSearch');
    if (question) { setQ(question); setSearch(question); setPage(0); sessionStorage.removeItem('knowledgeSearch'); }
  }, [active]);
  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(q);
      setPage(0);
    }, 250);
    return () => clearTimeout(t);
  }, [q]);
  async function upload(e) {
    try {
      const files = await encodeFiles(e.target.files);
      if (!files.length) return;
      setUploadNote('正在读取并导入资料…');
      const out = await run('page.kb.import', {
        archive: r.data.archive,
        files
      });
      if (out) {
        setUploadNote(out.message + (out.importResult?.failed?.length ? '；' + out.importResult.failed.map(x => x.file + ': ' + x.reason).join('；') : ''));
        r.refresh();
      } else setUploadNote('导入未完成，请查看操作提示。');
    } catch (error) {
      setUploadNote(error.message);
    }
    e.target.value = '';
  }
  return <><Header title="资料库" description="维护业务事实，让回复有据可查">
    <B icon={ArrowClockwise} onClick={r.refresh}>刷新</B>
    <B icon={DownloadSimple} disabled={!r.data || busy} onClick={() => setImaOpen(true)}>同步 ima</B>
    <B icon={Robot} disabled={!r.data || busy} onClick={() => setIngest(true)}>AI 整理</B>
    <B icon={UploadSimple} disabled={!r.data || busy} onClick={() => input.current.click()}>导入文件</B>
    <B tone="primary" icon={Plus} disabled={!r.data || busy} onClick={() => setEntry({})}>新增问答</B>
    <input hidden type="file" multiple ref={input} accept=".txt,.md,.csv,.xlsx,.xlsm,.xls,.docx" onChange={upload} />
  </Header>
  {imaOpen && r.data && <ImaSync api={api} archive={r.data.archive} run={run} busy={busy}
    onClose={() => setImaOpen(false)} onSynced={r.refresh} />}
  <ArchiveBar data={r.data} run={run} busy={busy} refresh={() => {
      setPage(0);
      r.refresh();
    }} /><div className="page-toolbar"><Search value={q} onChange={setQ} placeholder="搜索整个资料库" /><B tone="quiet" onClick={()=>setUnansweredOpen(true)}>常见转人工问题</B><span className="toolbar-note">{r.data?.total ?? '—'} 条资料</span><B tone="quiet toolbar-end" disabled={!r.data || busy} onClick={() => setConfirm({
        action: 'rebuild'
      })}>重建索引</B></div>{uploadNote && <div className="inline-note" role="status">{uploadNote}</div>}<LoadState resource={r}>{d => d.rows.length ? <><div className="table-scroll knowledge-table"><table><thead><tr><th>问题 / 资料</th><th>回答</th><th>来源</th><th>操作</th></tr></thead><tbody>{d.rows.map(row => <tr key={row.id}><td><button className="cell-link" onClick={() => setEntry(row)}>{row.faq ? row.question : '[整段资料] ' + row.text}</button></td><td><button className="cell-link secondary-text" onClick={() => setEntry(row)}>{row.faq ? row.answer : '点击查看全文'}</button></td><td className="source-cell">{row.source || '手动添加'}</td><td><div className="row-actions"><B icon={PencilSimple} aria-label={'编辑：' + (row.question || '整段资料')} disabled={busy} onClick={() => setEntry(row)} /><B icon={ArrowCounterClockwise} aria-label="撤销上次修改" disabled={busy} onClick={() => setConfirm({
                      action: 'undo',
                      row
                    })} /><B icon={Trash} aria-label="删除资料" disabled={busy} onClick={() => setConfirm({
                      action: 'delete',
                      row
                    })} /></div></td></tr>)}</tbody></table></div><Pagination page={d.page ?? page} total={d.total} onPage={setPage} /></> : <Empty title={search ? '没有匹配的资料' : '还没有资料'} text="可以导入文件，或手动新增一条问答" />}</LoadState>{r.data?.files?.length > 0 && <details className="source-files"><summary>已上传的源文件 · {r.data.files.length} 份</summary>{r.data.files.map(file=><div key={file.name}><strong>{file.name}</strong><span>{file.size_kb} KB</span><time>{file.mtime}</time></div>)}</details>}{entry && <EntryEditor entry={entry} archive={r.data.archive} run={run} busy={busy} onClose={() => setEntry(null)} onSaved={() => {
      setEntry(null);
      r.refresh();
    }} />}{confirm && <Confirm title={{
      delete: '删除这条资料？',
      undo: '撤销上次修改？',
      rebuild: '重建整个资料库索引？'
    }[confirm.action]} busy={busy} danger={confirm.action !== 'undo'} onClose={() => setConfirm(null)} onConfirm={async () => {
      if (await run('page.kb.' + confirm.action, {
        archive: r.data.archive,
        id: confirm.row?.id,
        revision: confirm.row?.revision
      })) {
        setConfirm(null);
        r.refresh();
      }
    }}>{confirm.action === 'rebuild' ? '将清空当前索引，并从原始文件重新生成。手动新增且没有源文件的内容不会保留，请确认后再继续。' : confirm.row?.text}</Confirm>}{unansweredOpen && <Unanswered api={api} run={run} busy={busy} onClose={()=>setUnansweredOpen(false)} onSaved={r.refresh}/>} {ingest && <Ingest archive={r.data.archive} run={run} busy={busy} onClose={() => setIngest(false)} onSaved={r.refresh} />}</>;
}
function ImaSync({ archive, api, run, busy, onClose, onSynced }) {
  const [wiki, setWiki] = useState('');
  const [clientId, setClientId] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [auto, setAuto] = useState(false);
  const [minutes, setMinutes] = useState('15');
  const [saved, setSaved] = useState(null);
  const [result, setResult] = useState(null);
  const [bases, setBases] = useState([]);
  useEffect(() => {
    api('resource?name=ima').then(data => {
      setWiki(data.wiki || ''); setAuto(data.auto); setMinutes(data.minutes); setSaved(data);
    }).catch(() => {});
  }, [api]);
  async function submit(action) {
    setResult(null);
    if (action === 'bases') {
      const out = await run('page.kb.ima_bases', { archive, clientId, apiKey });
      if (out) {
        setBases(out.bases || []); setResult(out);
        if (out.bases?.length === 1) setWiki(out.bases[0].id);
      }
      return;
    }
    if (action === 'test') {
      const out = await run('page.kb.ima_test', { archive, wiki, clientId, apiKey });
      if (out) setResult(out);
      return;
    }
    const out = await run('page.kb.ima_save', { archive, wiki, clientId, apiKey, auto, minutes });
    if (!out) return;
    setSaved(out); setClientId(''); setApiKey(''); setResult(out);
    if (action === 'sync') {
      const synced = await run('page.kb.ima_saved_sync', { archive });
      if (synced) { setResult(synced); onSynced(); }
    }
  }
  return <Modal title="同步 ima 知识库" onClose={onClose}>
    <p className="muted">将团队维护的客服问答同步到独立资料库，切换到该档案后用于回复。</p>
    <div className="form-stack">
      <B disabled={busy} onClick={() => submit('bases')}>读取我的知识库</B>{bases.length > 0 && <label>选择知识库<select value={wiki} disabled={busy} onChange={e => setWiki(e.target.value)}><option value="">请选择</option>{bases.map(base => <option key={base.id} value={base.id}>{base.name}</option>)}</select></label>}<label>知识库链接或 ID<input value={wiki} onChange={e => setWiki(e.target.value)} disabled={busy} placeholder="https://ima.qq.com/wikis?knowledgeBaseId=…" /></label>
      <label>ima Client ID<input value={clientId} onChange={e => setClientId(e.target.value)} disabled={busy} autoComplete="off" placeholder={saved?.configured ? '已保存，留空沿用' : '输入 Client ID'}/></label>
      <label>ima API Key<input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} disabled={busy} autoComplete="new-password" placeholder={saved?.configured ? '已保存，留空沿用' : '输入 API Key'}/></label>
      <label className="check-label"><input type="checkbox" checked={auto} onChange={e => setAuto(e.target.checked)} disabled={busy}/>软件运行时自动同步</label>
      <label>同步间隔（分钟）<input type="number" min="5" max="1440" value={minutes} onChange={e => setMinutes(e.target.value)} disabled={busy}/></label>
    </div>
    <p className="muted"><a href="https://ima.qq.com/agent-interface" target="_blank" rel="noreferrer">获取 ima 凭证</a></p>
    {saved?.last?.time && <p className="muted">上次同步 {saved.last.time} · {saved.last.ok ? saved.last.chunks + ' 条' : saved.last.error}</p>}
    {result && <div className="inline-note" role="status"><div>{result.message}</div>{Array.isArray(result.files) && <div>发现 {result.files.length} 份正式问答</div>}{result.importResult?.failed?.map(file => <div key={file.file}>{file.file} · {file.reason}</div>)}</div>}
    <div className="dialog-actions">
      <B disabled={busy || !wiki.trim()} onClick={() => submit('test')}>测试连接</B>
      <B disabled={busy || !wiki.trim()} onClick={() => submit('save')}>保存设置</B>
      <B tone="primary" icon={DownloadSimple} disabled={busy || !wiki.trim()} onClick={() => submit('sync')}>{busy ? '正在同步…' : '保存并同步'}</B>
    </div>
  </Modal>;
}

function Ingest({
  archive,
  run,
  busy,
  onClose,
  onSaved
}) {
  const [plan, setPlan] = useState(null),
    [rows, setRows] = useState(null),
    [error, setError] = useState(''),
    [done, setDone] = useState(false);
  return <Modal wide title="AI 整理成问答" onClose={onClose}><p className="muted">先核对原文，再选择要写入的问答。未选中的条目不会进入资料库。</p>{!plan && <label className="upload-zone"><UploadSimple size={28} /><strong>选择一份资料</strong><span>支持文本、CSV、Excel 与 Word</span><input type="file" accept=".txt,.md,.csv,.xlsx,.xlsm,.xls,.docx" disabled={busy} onChange={async e => {
        try {
          const files = await encodeFiles(e.target.files);
          const out = await run('page.ingest.plan', {
            archive,
            files
          });
          if (out) setPlan(out);
        } catch (error) {
          setError(error.message);
        }
      }} /></label>}{error && <div className="inline-note error">{error}</div>}{plan && !rows && <div className="ingest-plan"><h3>共 {plan.total} 块，将整理前 {plan.planned} 块</h3><p>每块调用一次已配置的模型接口。{plan.total > plan.planned && `剩余 ${plan.total - plan.planned} 块本次不整理，请拆分文件后继续。`}</p><B tone="primary" icon={Play} disabled={busy} onClick={async () => {
        const out = await run('page.ingest.run', {
          archive,
          planId: plan.planId
        });
        if (out) setRows(out.entries.map((r, index) => ({
          ...r,
          index,
          picked: r.ok
        })));
      }}>{busy ? '正在整理，请稍候…' : '开始整理'}</B></div>}{rows && <><div className="ingest-list">{rows.map((row, index) => <div className="ingest-row" key={index}><label className="check-label"><input type="checkbox" checked={row.picked} disabled={done || busy} onChange={e => setRows(old => old.map((x, i) => i === index ? {
              ...x,
              picked: e.target.checked
            } : x))} />问答 {index + 1}{!row.ok && <span className="warning-text">需要核对 · {row.problems.join('；')}</span>}</label><details><summary>查看对应原文</summary><pre className="prose">{row.chunk}</pre></details><div className="form-stack"><label>问题<input value={row.question} disabled={done || busy} onChange={e => setRows(old => old.map((x, i) => i === index ? {
                ...x,
                question: e.target.value
              } : x))} /></label><label>回答<textarea value={row.answer} disabled={done || busy} onChange={e => setRows(old => old.map((x, i) => i === index ? {
                ...x,
                answer: e.target.value
              } : x))} /></label></div></div>)}</div><div className="dialog-actions"><span className="muted">已选 {rows.filter(r => r.picked).length} / {rows.length} 条</span><B tone="primary" disabled={busy || done || !rows.some(r => r.picked)} onClick={async () => {
          if (await run('page.ingest.commit', {
            archive,
            planId: plan.planId,
            entries: rows.filter(r => r.picked)
          })) {
            setDone(true);
            onSaved();
          }
        }}>{done ? '已写入' : busy ? '正在写入…' : '确认内容并写入选中项'}</B></div></>}</Modal>;
}
function Prompts({
  api,
  run,
  busy,
  active
}) {
  const r = useResource(api, 'prompts', {}, active);
  const [key, setKey] = useState('system'),
    [drafts, setDrafts] = useState({}),
    [reset, setReset] = useState(false);
  const current = r.data?.prompts.find(p => p.key === key);
  const draft = current && (drafts[r.data.archive + ':' + key] || {
    text: current.text,
    revision: current.revision
  });
  const dirty = current && draft.text !== current.text;
  const stale = current && draft.revision !== current.revision;
  async function save(action) {
    const out = await run('page.prompt.' + action, {
      archive: r.data.archive,
      key,
      text: draft.text,
      revision: draft.revision
    });
    if (out) {
      setDrafts(old => {
        const next = {
          ...old
        };
        delete next[r.data.archive + ':' + key];
        return next;
      });
      setReset(false);
      r.refresh();
    }
  }
  return <><Header title="提示词" description="调整回复方式，保留业务约束与必需占位符"><B icon={ArrowClockwise} onClick={r.refresh}>重新读取</B><B disabled={!current || busy} onClick={() => setReset(true)}>恢复默认</B><B tone="primary" icon={FloppyDisk} disabled={!current || busy || stale} onClick={() => save('save')}>{busy ? '保存中…' : '保存并生效'}</B></Header><ArchiveBar data={r.data} run={run} busy={busy} refresh={r.refresh} /><LoadState resource={r}>{d => <><div className="prompt-tabs">{d.prompts.map(p => <button key={p.key} className={key === p.key ? 'active' : ''} onClick={() => setKey(p.key)}>{p.label.split('（')[0]}</button>)}</div>{current && <div className="prompt-layout"><section className="prompt-editor"><div className="section-heading"><h2>{current.label}</h2><span>{dirty ? '有未保存的改动' : '已与本机配置同步'}</span></div>{current.required.length > 0 && <div className="inline-note">必须保留：{current.required.join('、')}</div>}{stale && <div className="inline-note error">本机内容已更新，请重新载入后编辑。<B onClick={() => setDrafts(old => {
                const n = {
                  ...old
                };
                delete n[d.archive + ':' + key];
                return n;
              })}>载入最新内容</B></div>}<textarea aria-label="提示词内容" spellCheck="false" value={draft.text} disabled={busy} onChange={e => setDrafts(old => ({
              ...old,
              [d.archive + ':' + key]: {
                text: e.target.value,
                revision: draft.revision
              }
            }))} /><div className="editor-footer">{draft.text.length.toLocaleString()} 字 · 保存后立即生效</div></section><aside className="prompt-guide"><h3><CheckCircle size={18} />受保护规则</h3><pre>{d.safety}</pre><p>右侧规则仅供查看。编辑完成后，建议在「试问一句」验证资料检索。</p></aside></div>}</>}</LoadState>{reset && <Confirm title="恢复当前提示词的默认内容？" busy={busy} onClose={() => setReset(false)} onConfirm={() => save('reset')}>当前提示词的自定义内容将被默认版本替换。</Confirm>}</>;
}
function Learned({
  navigate,
  api,
  run,
  busy,
  active
}) {
  const r = useResource(api, 'learned', {}, active);
  const reviews = useResource(api, 'learning', {}, active);
  const [review, setReview] = useState(null);
  useEffect(() => { if (!active) return; const timer = setInterval(reviews.refresh, 3000); return () => clearInterval(timer); }, [active]);
  const importInput = useRef(null);
  const [importError, setImportError] = useState('');
  const [factQuestion, setFactQuestion] = useState('');
  const [factAnswer, setFactAnswer] = useState('');
  const [confirm, setConfirm] = useState(null),
    [preview, setPreview] = useState(false);
  useEffect(() => {
    if (confirm?.action === 'fact.accept') {
      setFactQuestion(confirm.row.question || ''); setFactAnswer(confirm.row.claim || '');
    }
  }, [confirm]);

  return <><Header title="学到的" description="检查从人工改稿中学习的语气与事实"><input type="file" accept=".json" hidden ref={importInput} onChange={async e => {
        const file = e.target.files?.[0];
        if (!file) return;
        try {
          setImportError('');
          const data = JSON.parse(await file.text());
          if (await run('page.review.import', { archive: r.data.archive, items: data.items })) r.refresh();
        } catch (error) { setImportError('文件无法读取，请选择完整的复核 JSON 文件。'); }
        e.target.value = '';
      }}/><B disabled={busy || !r.data} onClick={() => importInput.current.click()}>导入历史复核稿</B><B icon={Eye} disabled={!r.data} onClick={() => setPreview(true)}>查看实际注入内容</B><B icon={ArrowClockwise} onClick={r.refresh}>刷新</B></Header>{importError && <p role="alert" className="inline-note error">{importError}</p>}<ArchiveBar data={r.data} run={run} busy={busy} refresh={r.refresh} /><LoadState resource={r}>{d => <><div className="learning-status"><div><h2>从人工改稿中学习</h2><p>语气规则 {d.counts.rules} · 口吻样本 {d.counts.tones} · 已屏蔽 {d.counts.blocked} · 已采纳 {d.counts.accepts}</p></div><label className="switch-label"><input type="checkbox" role="switch" aria-label="从人工改稿中学习" checked={d.enabled} disabled={busy} onChange={async e => {
              if (await run('page.learn.toggle', {
                archive: d.archive,
                enabled: e.target.checked
              })) r.refresh();
            }} /><span>{d.enabled ? '已开启' : '已关闭'}</span></label></div><section className="data-panel"><div className="section-heading"><h2>回复学习记录</h2></div>{(reviews.data?.reviews || []).slice().reverse().map(row => <article className="learning-review-row" key={row.id}><div><strong>{row.question || '未记录问题'}</strong><p>{row.answer}</p><small>{row.receipt?.label || row.status} · {row.updated}</small></div>{(row.status === 'ready' || (row.status === 'learned' && !row.selected?.includes('reply'))) && <B disabled={busy} onClick={() => setReview(row)}>{row.status === 'learned' ? '继续学习问答' : '确认学习'}</B>}</article>)}{!reviews.data?.reviews?.length && <p className="muted">手动回复成功发送后，可在这里查看或继续学习。</p>}</section><section className="data-panel"><div className="section-heading"><h2>语气与口吻</h2><span>{d.rows.length} 条</span></div>{d.rows.length ? <div className="table-scroll"><table><thead><tr><th>类型</th><th>学到的内容</th><th>采纳次数</th><th>操作</th></tr></thead><tbody>{d.rows.map(row => <tr key={row.kind + row.id}><td><span className="table-tag">{row.label}</span></td><td className="wrap-cell">{row.text}</td><td>{row.hits || 1}</td><td><div className="row-actions"><B disabled={busy} onClick={() => setConfirm({
                        action: 'learn.block',
                        row,
                        title: '屏蔽这条学习内容？'
                      })}>不再学习</B><B icon={Trash} aria-label="删除学习记录" disabled={busy} onClick={() => setConfirm({
                        action: 'learn.delete',
                        row,
                        title: '删除这条学习记录？'
                      })} /></div></td></tr>)}</tbody></table></div> : <Empty title="还没有学习记录" text="人工编辑回复并成功发送后，学习结果会显示在这里" />}</section><section className="data-panel"><div className="section-heading"><div><h2>待确认的业务事实</h2><p>只有你确认后才会加入资料库</p></div><span>{d.facts.length} 条</span></div>{d.facts.map(row => <article className="fact-row" key={row.id}><div><h3>{row.question || '未记录问题'}</h3><p>{row.claim}</p><small>{row.source || '人工改稿学到'} · {row.ts}</small>{row.review && <details className="source-files"><summary>查看复核依据与待核实条件</summary><p>{row.review.reason}</p><p>需核实 · {row.review.needed}</p><p>原始归档行号 · {row.review.source_lines}</p></details>}</div><div className="row-actions"><B tone="quiet" disabled={busy} onClick={() => setConfirm({
                action: 'fact.reject',
                row,
                title: '拒绝这条业务事实？'
              })}>拒绝</B><B tone="primary" disabled={busy} onClick={() => setConfirm({
                action: 'fact.accept',
                row,
                title: '确认事实并加入资料库？'
              })}>采纳入库</B></div></article>)}{!d.facts.length && <Empty title="暂无待确认事实" />}</section><section className="data-panel"><div className="section-heading"><h2>已处理的业务事实</h2><span>{d.factHistory?.length || 0} 条</span></div>{(d.factHistory || []).map(row => <article className="learning-review-row" key={row.id}><div><strong>{row.published?.question || row.question}</strong><p>{row.published?.answer || row.claim}</p><small>{row.status === 'accepted' ? '已采纳入库' : '已拒绝'} · {row.decided}</small></div>{row.entry_id && <B onClick={() => { sessionStorage.setItem('knowledgeSearch', row.published?.question || row.question || ''); navigate('knowledge'); }}>已保存条目</B>}</article>)}{!d.factHistory?.length && <p className="muted">采纳或拒绝后，处理结果会保留在这里。</p>}</section></>}</LoadState>{review && <ReplyReview review={review} run={run} busy={busy} onClose={() => setReview(null)} onSaved={() => { reviews.refresh(); r.refresh(); }}/>}{preview && <Modal title="实际注入给 AI 的内容" wide onClose={() => setPreview(false)}><pre className="prose">{r.data.preview || '当前没有注入学习内容'}</pre></Modal>}{confirm && <Confirm title={confirm.title} busy={busy} onClose={() => setConfirm(null)} onConfirm={async () => {
      if (await run('page.' + confirm.action, {
        archive: r.data.archive,
        id: confirm.row.id,
        kind: confirm.row.kind,
        ...(confirm.action === 'fact.accept' ? { question: factQuestion, answer: factAnswer } : {})
      })) {
        setConfirm(null);
        r.refresh();
      }
    }}>{confirm.action === 'fact.accept' ? <div className="form-stack"><label>适用游戏与问题<input value={factQuestion} onChange={e => setFactQuestion(e.target.value)} maxLength={2000}/></label><label>核实后的完整答案<textarea value={factAnswer} onChange={e => setFactAnswer(e.target.value)} rows={6} maxLength={10000}/></label>{confirm.row.review && <p className="muted">需要核实 · {confirm.row.review.needed}</p>}<p>请核对当前游戏、版本、区服及活动条件，确认后立即用于回复。</p></div> : <p>{confirm.row.text || confirm.row.claim}</p>}</Confirm>}</>;
}
function Probe({
  api,
  run,
  busy,
  active
}) {
  const r = useResource(api, 'probe', {}, active);
  const [question, setQuestion] = useState(''),
    [result, setResult] = useState(null);
  return <><Header title="试问一句" description="用客户的问法检查资料命中情况，不会向客户发送消息" /><ArchiveBar data={r.data} run={run} busy={busy} refresh={() => {
      setResult(null);
      r.refresh();
    }} /><form className="probe-form" onSubmit={async e => {
      e.preventDefault();
      const out = await run('page.probe.run', {
        archive: r.data.archive,
        question
      });
      if (out) setResult({
        ...out,
        question
      });
    }}><label htmlFor="probe-question">客户可能会问</label><div><input id="probe-question" value={question} onChange={e => setQuestion(e.target.value)} placeholder="例如：账号登录失败应该怎么处理？" /><B type="submit" tone="primary" icon={MagnifyingGlass} disabled={!r.data || !question.trim() || busy}>{busy ? '正在检索…' : '测试检索'}</B></div><p>使用当前资料库与实际检索链路。首次加载本地模型可能需要几秒。</p></form><LoadState resource={r}>{() => result ? <section className="probe-results"><div className="section-heading"><h2>检索结果</h2><span>自动回复阈值 {result.threshold?.toFixed(2)} · {result.hits.length} 条命中</span></div>{result.hits.map((hit, i) => <article className="probe-hit" key={hit.id || i}><div className="hit-number">{i + 1}</div><div><div className="hit-heading"><h3>{hit.question || '整段资料'}</h3><span>{Number(hit.score).toFixed(3)}</span><b>{hit.verdict}</b></div><p>{hit.answer || hit.text}</p><small>来源：{hit.source || '手动添加'}</small></div></article>)}{!result.hits.length && <Empty title="没有检索到匹配资料" text="请补充相关资料，或换一种客户常用的问法" />}</section> : <Empty title="输入一个真实的客户问题" text="查看命中的原文、匹配度与判断结果，确认资料是否覆盖这个问题" />}</LoadState></>;
}
function Settings({
  api,
  run,
  busy,
  active
}) {
  const r = useResource(api, 'settings', {}, active);
  const [values, setValues] = useState(null),
    [saved, setSaved] = useState({}),
    [models, setModels] = useState([]),
    [note, setNote] = useState(''),
    [confirm, setConfirm] = useState(null),
    [clearSecrets, setClearSecrets] = useState({}),
    [restart, setRestart] = useState(false),
    [help, setHelp] = useState(false);
  useEffect(() => {
    if (r.data && !values) {
      setValues(r.data.values);
      setSaved(r.data.savedSecrets);
      setModels(r.data.values.llm_model ? [r.data.values.llm_model] : []);
    }
  }, [r.data]);
  function field(key, value) {
    setValues(old => ({
      ...old,
      [key]: value,
      ...(['llm_base_url', 'llm_api_key'].includes(key) ? {
        llm_model: ''
      } : {})
    }));
    if (['llm_base_url', 'llm_api_key'].includes(key)) setModels([]);
    if (key === 'llm_base_url') {
      setSaved(old => ({
        ...old,
        llm_api_key: false
      }));
      setClearSecrets(old => ({
        ...old,
        llm_api_key: true
      }));
      setValues(old => ({
        ...old,
        llm_api_key: ''
      }));
    }
  }
  async function action(name, extra = {}) {
    const out = await run('page.settings.' + name, {
      values,
      clearSecrets,
      ...extra
    });
    if (out) {
      setNote(out.message);
      if (out.models) {
        setModels(out.models);
        setValues(old => ({
          ...old,
          llm_model: out.models.includes(old.llm_model) ? old.llm_model : out.models[0] || ''
        }));
      }
      if (name === 'save') {
        setRestart(out.software_changed);
        setSaved(old => ({
          ...old,
          llm_api_key: !!values.llm_api_key || !clearSecrets.llm_api_key && old.llm_api_key,
          wecom_kf_secret: !!values.wecom_kf_secret || !clearSecrets.wecom_kf_secret && old.wecom_kf_secret
        }));
        setValues(old => ({
          ...old,
          llm_api_key: '',
          wecom_kf_secret: ''
        }));
        setClearSecrets({});
        setConfirm(null);
      }
    }
  }
  const v = values || {};
  return <><Header title="设置" description="配置模型接口与消息接入方式"><B icon={ArrowClockwise} disabled={busy} onClick={() => {
        setValues(null);
        setNote('');
        r.refresh();
      }}>重新读取</B></Header><LoadState resource={r}>{d => <><div className="settings-layout"><nav className="settings-outline"><a href="#model-settings">模型接口</a><a href="#channel-settings">接入通道</a>{v.software === 'wecom_api' && <a href="#wecom-settings">企业微信凭据</a>}<a href="#application-settings">应用</a></nav><div className="settings-sections"><section id="model-settings" className="settings-section"><div className="section-heading"><div><h2>模型接口</h2><p>支持 OpenAI 兼容接口，保存后立即生效</p></div></div><div className="form-stack"><label>服务预设<select aria-label="服务预设" onChange={e => {
                    const preset = d.presets.find(x => x[0] === e.target.value);
                    if (preset?.[1]) field('llm_base_url', preset[1]);
                  }} defaultValue=""><option value="" disabled>选择预设或使用自定义地址</option>{d.presets.map(p => <option key={p[0]}>{p[0]}</option>)}</select></label><label>接口地址<input value={v.llm_base_url || ''} onChange={e => field('llm_base_url', e.target.value)} placeholder="https://api.example.com/v1" autoComplete="off" /></label><label>API Key<input type="password" value={v.llm_api_key || ''} onChange={e => field('llm_api_key', e.target.value)} placeholder={saved.llm_api_key ? '已保存，留空保持当前密钥' : '填写你申请的 API Key'} autoComplete="new-password" /></label>{saved.llm_api_key && <label className="check-label"><input type="checkbox" checked={!!clearSecrets.llm_api_key} onChange={e => setClearSecrets(old => ({
                    ...old,
                    llm_api_key: e.target.checked
                  }))} />清除已保存的模型密钥</label>}<label>模型<div className="input-actions"><select aria-label="模型" value={v.llm_model || ''} onChange={e => field('llm_model', e.target.value)}><option value="">请选择模型</option>{models.map(m => <option key={m}>{m}</option>)}</select><B disabled={busy || !v.llm_base_url} onClick={() => action('models')}>拉取模型</B><B disabled={busy || !v.llm_model} onClick={() => action('test')}>测试连接</B></div></label></div></section><section id="channel-settings" className="settings-section"><div className="section-heading"><div><h2>接入通道</h2><p>切换接入通道需要重启程序</p></div><B onClick={r.refresh}>刷新列表</B></div><div className="channel-options">{d.channels.map(([id, label, available, description]) => <label className={'channel-option' + (v.software === id ? ' chosen' : '')} key={id}><input type="radio" name="software" checked={v.software === id} disabled={!available || busy} onChange={() => field('software', id)} /><span><strong>{label}</strong><small>{description || '可使用'}</small></span>{v.software === id && <CheckCircle size={20} />}</label>)}</div><B tone="quiet" onClick={() => setHelp(true)}>如何接入其他聊天软件？</B></section>{v.software === 'wecom_api' && <section id="wecom-settings" className="settings-section"><div className="section-heading"><div><h2>企业微信「微信客服」凭据</h2><p>使用微信客服应用的 Secret，不是自建应用的 Secret</p></div></div><div className="form-stack">{[['wecom_corp_id', '企业 ID'], ['wecom_kf_secret', '客服 Secret'], ['wecom_open_kfid', '客服账号 ID']].map(([key, label]) => <label key={key}>{label}<input type={key.includes('secret') ? 'password' : 'text'} value={v[key] || ''} autoComplete="off" placeholder={saved[key] ? '已保存，留空保持当前值' : ''} onChange={e => field(key, e.target.value)} /></label>)}<label className="check-label"><input type="checkbox" checked={!!clearSecrets.wecom_kf_secret} onChange={e=>setClearSecrets(old=>({...old,wecom_kf_secret:e.target.checked}))}/>清除已保存的客服 Secret</label><B disabled={busy} onClick={() => action('wecom_test')}>测试企业微信连接</B></div></section>}<section id="application-settings" className="settings-section"><div className="section-heading"><div><h2>应用</h2><p>本机运行 · 退出程序将停止消息采集和自动回复</p></div></div><div className="application-actions"><B disabled={busy} onClick={() => setConfirm('restart')}>重启程序</B><B tone="quiet" disabled={busy} onClick={() => setConfirm('exit')}>退出程序</B></div></section></div></div><footer className="settings-save"><span role="status">{busy ? '正在处理，请稍候…' : note || '未保存的修改不会生效'}</span>{restart && <B onClick={() => setConfirm('restart')}>立即重启</B>}<B icon={FloppyDisk} tone="primary" disabled={busy || !values} onClick={() => {
            if (!v.llm_api_key && (!saved.llm_api_key || clearSecrets.llm_api_key)) setConfirm('empty');else action('save');
          }}>保存设置</B></footer></>}</LoadState>{confirm && <Confirm title={confirm === 'empty' ? '保存空模型密钥？' : confirm === 'exit' ? '退出客服程序？' : '重启客服程序？'} busy={busy} danger={confirm === 'exit'} onClose={() => setConfirm(null)} onConfirm={async () => {
      if (confirm === 'empty') await action('save', {
        allowEmptyKey: true
      });else if (await run(confirm)) setConfirm(null);
    }}>{confirm === 'empty' ? '没有有效密钥时无法启动自动回复。' : confirm === 'exit' ? '程序退出后将停止消息采集和自动回复。' : '当前服务将停止，新窗口启动后需重新点击开始。请先保存设置。'}</Confirm>}{help && <Modal title="接入其他聊天软件" onClose={() => setHelp(false)}><ol className="help-steps"><li>打开并登录需要接入的聊天软件。</li><li>在源码环境运行 scripts/calibrate_chat_app.py，按提示选择窗口和聊天区。</li><li>把生成的标定文件放入程序的 profiles 目录。</li><li>刷新通道列表，选择对应软件，保存并重启。</li></ol><p className="muted">已存在的标定文件会自动出现在通道列表中。</p></Modal>}</>;
}
const components = {
  all: History,
  replied: History,
  assistant: AssistantPage,
  dashboard: Dashboard,
  knowledge: Knowledge,
  prompts: Prompts,
  learned: Learned,
  probe: Probe,
  settings: Settings
};
export function PageRouter(props) {
  const [visited, setVisited] = useState([props.page]);
  useEffect(() => setVisited(old => old.includes(props.page) ? old : [...old, props.page]), [props.page]);
  return <section className="page-area" hidden={props.page === 'pending'}><div className="page-topline"><BookOpen size={18} /><span>{names[props.page]}</span><span className="page-local">本机工作区</span></div>{props.demo && <div className="preview-note">演示模式 · 示例数据不会写入真实配置或资料库</div>}{props.connectionError && <div className="notice error">{props.connectionError}</div>}<div className="page-content">{visited.map(page => {
        const Component = components[page];
        return Component && <div key={page} hidden={props.page !== page} className="page-view"><PageBoundary title={names[page]}><Component {...props} page={page} active={props.page === page} /></PageBoundary></div>;
      })}</div></section>;
}
