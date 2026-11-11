'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const e = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
const icons = {search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',download:'<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>'};
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || ''}</svg>`;
const state = {data:null,page:'overview',scope:'open',selectedId:null,journalDetail:null,filters:{search:'',status:'',priority:''},knowledge:{search:'',category:''}};
const pageNames = {overview:'Обращения',knowledge:'База знаний',analytics:'Статистика',detail:'Обращение'};
const requests = {journal:0};
const pendingIncidents = new Set();
let toastTimer;
function toast(message) { $('#toast').textContent=message; $('#toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('#toast').hidden=true,5500); }
async function api(path,method='GET',data) {
  let response;
  try { response=await fetch(path,{method,...(data?{headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}:{})}); }
  catch { throw new Error('Нет связи с журналом. Попробуйте обновить страницу.'); }
  const body=await response.json();
  if(!response.ok)throw new Error(body.error || 'Не удалось выполнить действие.');
  return body;
}
async function refresh() {
  state.data=await api('/api/bootstrap');
  $('.edition-mode').textContent=state.data.environment?.public?'Учебный онлайн-стенд':'Локальный сеанс';
  $('#storage-note').textContent=state.data.environment?.public?'Общая учебная база. Используйте только вымышленные данные.':'Данные хранятся на этом компьютере.';
  $('#nav-count').textContent=state.data.incidents.filter(i=>i.status!=='resolved').length;
  $('#article-category').innerHTML=options(state.data.categories);
  $('#services').innerHTML=[...new Set(state.data.incidents.map(i=>i.service))].map(s=>`<option value="${e(s)}"></option>`).join('');
}
function options(values,placeholder) { return (placeholder?`<option value="">${placeholder}</option>`:'')+Object.entries(values).map(([key,value])=>`<option value="${e(key)}">${e(value)}</option>`).join(''); }
function stamp(date,time=false) { return new Intl.DateTimeFormat('ru-RU',{day:'2-digit',month:'short',...(time?{hour:'2-digit',minute:'2-digit'}:{})}).format(new Date(date)); }
function incidentNumber(id) { return `INC-${String(id).padStart(4,'0')}`; }
function priorityBadge(i) { return `<span class="priority ${e(i.priority)}">${e(state.data.priorities[i.priority])}</span>`; }
function statusBadge(i) { return `<span class="status ${e(i.status)}">${e(state.data.statuses[i.status])}</span>`; }
function demoTag(i) { return i.is_demo?'<span class="demo-tag">ДЕМО</span>':''; }
function demoNotice() {
  const count=state.data.incidents.filter(i=>i.is_demo).length;
  return count?`<div class="demo-banner"><b>Учебный набор</b><span>${count} демонстрационных обращений отмечены «Демо» и включены в статистику.</span></div>`:'';
}
function actions() { return '<button class="button primary" data-action="new-incident">Новое обращение <span aria-hidden="true">+</span></button>'; }
function heading(number,title,description,buttons=actions()) { return `<div class="page-heading"><div><h1>${title}</h1><p>${description}</p></div>${buttons?`<div class="heading-actions">${buttons}</div>`:''}</div>`; }
function activeIncidents() {
  const priorityOrder=['critical','high','medium','low'];
  return state.data.incidents.filter(i=>i.status!=='resolved').sort((a,b)=>priorityOrder.indexOf(a.priority)-priorityOrder.indexOf(b.priority)||new Date(b.created_at)-new Date(a.created_at));
}
function renderJournal() { return renderIncidents(); }
function workflow(i) {
  if(i.status==='new')return '<p>Начните с рекомендованной инструкции.</p><button class="button primary" data-transition="in_progress">Взять в работу</button>';
  if(i.status==='in_progress')return '<p>Обращение в работе. После проверки сохраните результат.</p><button class="button primary" data-action="show-resolution">Записать решение</button>';
  return '<p>Обращение решено. Если проблема повторилась, откройте его снова.</p><button class="button secondary" data-transition="in_progress">Вернуть в работу</button>';
}
function record(result) {
  const i=result.incident,a=i.analysis,first=a.recommendations[0];
  const instruction=(r,index)=>`<details class="recommendation"><summary><span class="instruction-number">${String(index+1).padStart(2,'0')}</span><span>${e(r.title)}</span></summary><ol class="steps">${r.steps.map(s=>`<li>${e(s)}</li>`).join('')}</ol></details>`;
  return `<article class="simple-record" data-incident-card="${i.id}"><div class="record-topline"><div class="record-kicker"><span class="record-id">${incidentNumber(i.id)}</span>${demoTag(i)}</div>${statusBadge(i)}</div><h1 class="record-title">${e(i.title)}</h1>
  <div class="case-essentials"><span>${e(i.service)}</span>${priorityBadge(i)}</div><p class="record-description">${e(i.description)}</p>
  <div class="next-action">${workflow(i)}</div><p class="form-error" data-record-error role="alert"></p>
  ${i.status==='in_progress'?'<details class="resolution-editor"><summary>Результат обработки</summary><form class="resolve-form" data-resolve-form><label>Что помогло решить проблему?<textarea name="resolution" required minlength="10" maxlength="5000" rows="3" placeholder="Опишите выполненные действия и результат проверки"></textarea></label><button class="button primary" type="submit">Сохранить и закрыть обращение</button></form></details>':''}
  ${i.resolution?`<section class="record-section"><h2>${i.status==='resolved'?'Решение':'Предыдущее решение'}</h2><p class="resolution-text">${e(i.resolution)}</p></section>`:''}
  ${investigationPanel(result.investigation,i)}
  ${result.investigation?.started?`<details class="folded-section"><summary>Инструкция первичного анализа</summary>  <section class="record-section primary-advice"><span class="eyebrow">${i.status==='resolved'?'Рекомендованная инструкция':'С чего начать'}</span>${first?`<h2>${e(first.title)}</h2><p class="advice-summary">${e(first.summary)}</p><details class="advice-steps"><summary>Показать шаги проверки (${first.steps.length})</summary><ol class="steps">${first.steps.map(s=>`<li>${e(s)}</li>`).join('')}</ol></details>`:'<h2>Нужна дополнительная диагностика</h2><p class="advice-summary">Подходящей инструкции пока нет. Уточните обстоятельства проблемы и зафиксируйте найденное решение.</p>'}</section></details>`:`  <section class="record-section primary-advice"><span class="eyebrow">${i.status==='resolved'?'Рекомендованная инструкция':'С чего начать'}</span>${first?`<h2>${e(first.title)}</h2><p class="advice-summary">${e(first.summary)}</p><details class="advice-steps"><summary>Показать шаги проверки (${first.steps.length})</summary><ol class="steps">${first.steps.map(s=>`<li>${e(s)}</li>`).join('')}</ol></details>`:'<h2>Нужна дополнительная диагностика</h2><p class="advice-summary">Подходящей инструкции пока нет. Уточните обстоятельства проблемы и зафиксируйте найденное решение.</p>'}</section>`}

  ${a.recommendations.length>1?`<details class="folded-section"><summary>Другие подходящие инструкции (${a.recommendations.length-1})</summary><div class="folded-content">${a.recommendations.slice(1).map((r,index)=>instruction(r,index+1)).join('')}</div></details>`:''}
  <details class="folded-section"><summary>Почему выбран такой приоритет?</summary><div class="folded-content explanation-grid"><div class="explanation-item"><h4>Категория: ${e(a.category_label)}</h4><p>${e(a.classification_reason)}</p><span class="confidence">${e(a.confidence)}</span></div><div class="explanation-item"><h4>Приоритет обработки</h4><p>${e(a.priority_reason)}</p></div></div></details>
  <details class="folded-section"><summary>Данные обращения</summary><dl class="detail-facts"><div><dt>Кого затронула проблема</dt><dd>${e(state.data.impacts[i.impact])}</dd></div><div><dt>Насколько мешает работе</dt><dd>${e(state.data.urgencies[i.urgency])}</dd></div><div><dt>Создано</dt><dd>${stamp(i.created_at,true)}</dd></div></dl><p class="section-note">Рекомендации сохранены при создании обращения. Проверьте их применимость перед выполнением.</p></details>
  <details class="folded-section"><summary>История обращения (${result.events.length})</summary><div class="history-list">${result.events.map(ev=>`<div class="event"><time datetime="${e(ev.created_at)}">${stamp(ev.created_at,true)}</time><p>${e(ev.text)}</p></div>`).join('')}</div></details></article>`;
}
function renderRecordPage() {
  return `<div class="record-page"><a class="back-link" href="#overview">← К списку обращений</a><div id="journal-detail" aria-live="polite">${state.journalDetail?.incident.id===state.selectedId?record(state.journalDetail):'<div class="initial-loading" role="status">Открываем обращение…</div>'}</div></div>`;
}
async function loadJournal(id) {
  state.selectedId=id;
  const request=++requests.journal;
  const container=$('#journal-detail');
  if(!container)return;
  container.setAttribute('aria-busy','true');
  try {
    const result=await api(`/api/incidents/${id}`);
    if(request!==requests.journal||state.page!=='detail'||state.selectedId!==id)return;
    state.journalDetail=result;container.innerHTML=record(result);
  } catch(err) {
    if(request===requests.journal&&state.page==='detail')container.innerHTML=`<div class="empty-state retry-message"><h2>Не удалось открыть обращение</h2><p>${e(err.message)}</p><button class="button secondary" data-retry-record="${id}">Повторить загрузку</button></div>`;
  } finally {if(request===requests.journal)container.removeAttribute('aria-busy');}
}
function filteredIncidents() {
  const f=state.filters;
  const list=state.scope==='open'?activeIncidents():state.data.incidents.filter(i=>state.scope!=='resolved'||i.status==='resolved');
  return list.filter(i=>(!f.status||i.status===f.status)&&(!f.priority||i.priority===f.priority)&&`${incidentNumber(i.id)} ${i.title} ${i.description} ${i.service}`.toLowerCase().includes(f.search.toLowerCase()));
}
function incidentRows(list) {
  if(!list.length){
    const filtering=state.filters.search||state.filters.priority;
    const title=filtering?'Ничего не найдено':state.scope==='resolved'?'Решённых обращений пока нет':state.scope==='all'?'Пока нет обращений':'Всё обработано';
    return `<div class="empty-state"><h2>${title}</h2><p>${filtering?'Попробуйте другое слово или сбросьте фильтры.':state.scope==='open'?'Открытых обращений нет. Новую проблему можно добавить кнопкой выше.':'Здесь появятся обращения после обработки.'}</p>${filtering?'<button class="button secondary" data-action="reset-filters">Сбросить поиск</button>':''}</div>`;
  }
  return list.map(i=>`<button class="case-row" data-open="${i.id}" aria-label="Открыть обращение: ${e(i.title)}"><span class="case-body"><span class="case-title">${e(i.title)}</span><span class="case-service">${e(i.service)}</span><span class="case-foot"><span>${incidentNumber(i.id)}</span><span>${stamp(i.created_at)}</span>${demoTag(i)}</span></span>${priorityBadge(i)}${statusBadge(i)}<span class="case-arrow" aria-hidden="true">↗</span></button>`).join('');
}
function renderIncidents() {
  const list=state.data.incidents;
  const scopes=[['open','Открытые',list.filter(i=>i.status!=='resolved').length],['resolved','Решённые',list.filter(i=>i.status==='resolved').length],['all','Все',list.length]];
  return `<div class="cases-page">${heading('01','Обращения','Выберите проблему из списка или создайте новое обращение.')}<div class="case-tools"><div class="scope-tabs" role="group" aria-label="Какие обращения показать">${scopes.map(([key,label,count])=>`<button class="scope-tab ${state.scope===key?'selected':''}" data-scope="${key}" aria-pressed="${state.scope===key}">${label}<span>${count}</span></button>`).join('')}</div><div class="case-search"><div class="search">${icon('search')}<input id="incident-search" aria-label="Найти обращение" placeholder="Найти обращение" value="${e(state.filters.search)}"></div><details class="extra-filters" ${state.filters.priority?'open':''}><summary>Фильтры${state.filters.priority?' · 1':''}</summary><label>Приоритет<select id="priority-filter" aria-label="Фильтр по приоритету">${options(state.data.priorities,'Любой приоритет')}</select></label></details></div></div><div class="cases-list" id="incident-results">${incidentRows(filteredIncidents())}</div><div class="case-list-footer"><span id="result-count">Показано: ${filteredIncidents().length}</span><a class="text-button" href="/api/export">Скачать список CSV</a></div>${demoNotice()}</div>`;
}
function articleEntries() {
  const f=state.knowledge;
  const filtered=state.data.articles.filter(a=>(!f.category||a.category===f.category)&&`${a.title} ${a.summary} ${a.keywords.join(' ')}`.toLowerCase().includes(f.search.toLowerCase()));
  return filtered.map(a=>`<article class="knowledge-entry"><div class="knowledge-meta"><span class="record-id">KB-${String(a.id).padStart(4,'0')}</span><span class="eyebrow">${e(state.data.categories[a.category])}</span></div><h2>${e(a.title)}</h2><p>${e(a.summary)}</p><details><summary>Последовательность проверки · ${a.steps.length} шагов</summary><ol class="steps">${a.steps.map(s=>`<li>${e(s)}</li>`).join('')}</ol></details><div class="keywords">${a.keywords.map(k=>`<span>${e(k)}</span>`).join('')}</div></article>`).join('')||'<div class="empty-state"><h3>Инструкций не найдено</h3>Попробуйте другое ключевое слово или категорию.</div>';
}
function renderKnowledge() {
  const button='<button class="button primary" data-action="new-article">Добавить инструкцию ↗</button>';
  return `${heading('03','База знаний','Готовые инструкции, которые помогут разобраться с типовой проблемой.',button)}<div class="knowledge-toolbar"><div class="search">${icon('search')}<input id="knowledge-search" aria-label="Поиск по базе знаний" placeholder="Найти инструкцию или ключевое слово" value="${e(state.knowledge.search)}"></div><select id="knowledge-category" aria-label="Категория инструкции">${options(state.data.categories,'Все категории')}</select></div><div class="knowledge-grid" id="article-results">${articleEntries()}</div>`;
}
function renderAnalytics() {
  const list=state.data.incidents,active=list.filter(i=>i.status!=='resolved'),resolved=list.filter(i=>i.status==='resolved');
  const categories=Object.entries(state.data.categories).map(([key,label])=>({label,n:list.filter(i=>i.category===key).length})).filter(r=>r.n).sort((a,b)=>b.n-a.n);
  const services=[...new Set(list.map(i=>i.service))].map(label=>({label,n:list.filter(i=>i.service===label).length})).sort((a,b)=>b.n-a.n);
  const bars=rows=>rows.map(r=>`<div class="bar-row"><span class="bar-label">${e(r.label)}</span><div class="bar-track" aria-hidden="true"><div class="bar-fill" style="width:${r.n/Math.max(...rows.map(x=>x.n),1)*100}%"></div></div><span class="bar-value">${r.n}</span></div>`).join('')||'<p class="section-note">Данных пока нет.</p>';
  const timed=resolved.filter(i=>i.resolved_at);
  const hours=timed.length?(timed.reduce((sum,i)=>sum+(new Date(i.resolved_at)-new Date(i.created_at))/3600000,0)/timed.length).toLocaleString('ru-RU',{maximumFractionDigits:1}):'—';
  const stats=[[list.length,'Всего записей','За всё время'],[active.length,'Открытые обращения',`${list.filter(i=>i.status==='in_progress').length} в работе`],[active.filter(i=>i.priority==='critical').length,'Критические','Среди открытых'],[resolved.length,'Решённые',`${list.length?Math.round(resolved.length/list.length*100):0}% от всех обращений`]];
  return `${heading('04','Отчёт по обращениям','Сводка по всем записям журнала, включая учебные примеры.',`<a class="button secondary" href="/api/export">${icon('download')} Выгрузить CSV</a>`)}${demoNotice()}<div class="stats-band">${stats.map(([n,label,note],index)=>`<div class="stat ${index===2?'attention':''}"><div class="stat-label">${label}</div><div class="stat-number">${n}</div><div class="stat-note">${note}</div></div>`).join('')}</div><div class="analytics-grid">
  <section class="report-section"><h2>По характеру проблемы</h2>${bars(categories)}</section><section class="report-section"><h2>По затронутому сервису</h2>${bars(services)}</section>
  <section class="report-section"><h2>Матрица приоритетов</h2><table class="matrix"><thead><tr><th scope="col">Влияние / срочность</th><th scope="col">Может подождать</th><th scope="col">Работа затруднена</th><th scope="col">Работа остановлена</th></tr></thead><tbody><tr><th scope="row">Один пользователь</th><td class="low">Низкий</td><td class="medium">Средний</td><td class="high">Высокий</td></tr><tr><th scope="row">Отдел / группа</th><td class="medium">Средний</td><td class="high">Высокий</td><td class="high">Высокий</td></tr><tr><th scope="row">Вся организация</th><td class="medium">Средний</td><td class="high">Высокий</td><td class="critical">Критический</td></tr></tbody></table><p class="chart-note">События безопасности получают приоритет не ниже высокого. Вывод модуля требует проверки администратором.</p></section>
  <section class="report-section"><h2>Ход обработки</h2><div class="flow-strip">${Object.entries(state.data.statuses).map(([key,label])=>`<div class="flow-box"><b>${list.filter(i=>i.status===key).length}</b><span>${e(label)}</span></div>`).join('')}</div><p class="metric-callout">${hours} ч — среднее время решения</p><p class="chart-note">По ${timed.length} обращениям, которые сейчас решены. Интервал от регистрации до последнего решения. Для повторно открытых записей учитывается весь период, включая учебные примеры.</p></section></div>`;
}
function render() {
  const route=location.hash.slice(1),detailRoute=/^incident\/([1-9]\d*)$/.exec(route);
  if(detailRoute){state.page='detail';state.selectedId=Number(detailRoute[1]);}
  else state.page=Object.hasOwn(pageNames,route)&&route!=='detail'?route:'overview';
  $('#breadcrumb').textContent=pageNames[state.page];
  $$('nav a[data-page]').forEach(a=>{const selected=a.dataset.page===(state.page==='detail'?'overview':state.page);a.classList.toggle('active',selected);if(selected)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  $('#main').innerHTML=({overview:renderJournal,detail:renderRecordPage,knowledge:renderKnowledge,analytics:renderAnalytics})[state.page]();
  if(state.page==='detail'&&state.journalDetail?.incident.id!==state.selectedId)loadJournal(state.selectedId);
  if(state.page==='overview')$('#priority-filter').value=state.filters.priority;
  if(state.page==='knowledge')$('#knowledge-category').value=state.knowledge.category;
}
function openCreate() {
  $('#incident-form').reset();$('#create-error').textContent='';
  $('details.analysis-preview',$('#incident-form')).open=false;
  $('#analysis-preview').innerHTML='<span class="eyebrow">Предварительный анализ</span><p>Заполните поля, чтобы проверить категорию, приоритет и наличие подходящих инструкций.</p>';
  $('#create-dialog').showModal();
}
function openDetail(id) {
  const hash=`#incident/${id}`;
  if(location.hash===hash)render();else location.hash=hash;
}
async function transition(card,status,resolution='') {
  const id=Number(card.dataset.incidentCard);
  if(pendingIncidents.has(id))return;
  pendingIncidents.add(id);
  $$('button,textarea',card).forEach(b=>b.disabled=true);
  $('[data-record-error]',card).textContent='';
  let saved=false;
  try {
    await api(`/api/incidents/${id}`,'PATCH',{status,resolution});saved=true;
    await refresh();state.journalDetail=null;render();
    toast(status==='resolved'?'Решение зафиксировано в журнале':'Обращение взято в работу');
  }catch(err){const message=saved?'Изменение сохранено. Обновите страницу, чтобы загрузить актуальный журнал.':err.message;if(card.isConnected)$('[data-record-error]',card).textContent=message;else toast(message);}
  finally{pendingIncidents.delete(id);$$('button,textarea',card).forEach(b=>b.disabled=false);}
}
function updateIncidentResults() {$('#incident-results').innerHTML=incidentRows(filteredIncidents());$('#result-count').textContent=`Показано: ${filteredIncidents().length}`;}
document.addEventListener('click',event=>{
  if(event.target.closest('.skip-link')){event.preventDefault();$('#main').focus();$('#main').scrollIntoView({block:'start'});return;}
  const close=event.target.closest('[data-close]');if(close){document.getElementById(close.dataset.close).close();return;}
  const scope=event.target.closest('[data-scope]');if(scope){state.scope=scope.dataset.scope;render();return;}
  const retry=event.target.closest('[data-retry-record]');if(retry){loadJournal(Number(retry.dataset.retryRecord));return;}
  const opened=event.target.closest('[data-open]');if(opened){openDetail(Number(opened.dataset.open));return;}
  const action=event.target.closest('[data-action]')?.dataset.action;
  if(action==='new-incident')openCreate();
  if(action==='reset-filters'){state.filters={search:'',status:'',priority:''};render();}
  if(action==='show-resolution'){const editor=$('.resolution-editor',event.target.closest('[data-incident-card]'));editor.open=true;$('textarea',editor).focus();editor.scrollIntoView({block:'center',behavior:'auto'});}
  if(action==='new-article'){$('#article-form').reset();$('#article-error').textContent='';$('#article-dialog').showModal();}
  const transitionButton=event.target.closest('[data-transition]');if(transitionButton)transition(transitionButton.closest('[data-incident-card]'),transitionButton.dataset.transition);
});
document.addEventListener('input',event=>{
  if(event.target.closest('#incident-form')&&['INPUT','TEXTAREA','SELECT'].includes(event.target.tagName))$('#analysis-preview').innerHTML='<span class="eyebrow">Предварительный анализ</span><p>Данные изменены. Проверьте анализ заново. При регистрации он будет рассчитан по актуальным полям.</p>';
  if(event.target.id==='incident-search'){state.filters.search=event.target.value;updateIncidentResults();}
  if(event.target.id==='knowledge-search'){state.knowledge.search=event.target.value;$('#article-results').innerHTML=articleEntries();}
});
document.addEventListener('change',event=>{
  if(['status-filter','priority-filter'].includes(event.target.id)){state.filters[event.target.id==='status-filter'?'status':'priority']=event.target.value;updateIncidentResults();}
  if(event.target.id==='knowledge-category'){state.knowledge.category=event.target.value;$('#article-results').innerHTML=articleEntries();}
});
document.addEventListener('submit',event=>{if(event.target.matches('[data-resolve-form]')){event.preventDefault();transition(event.target.closest('[data-incident-card]'),'resolved',new FormData(event.target).get('resolution'));}});
$('#preview-analysis').addEventListener('click',async event=>{
  const form=$('#incident-form');if(!form.reportValidity())return;
  const button=event.currentTarget;button.disabled=true;$('#create-error').textContent='';
  const payload=Object.fromEntries(new FormData(form));
  try{const a=await api('/api/analyze','POST',payload);if(JSON.stringify(payload)!==JSON.stringify(Object.fromEntries(new FormData(form))))return;$('#analysis-preview').innerHTML=`<span class="eyebrow">Результат анализа</span><div class="preview-result-title"><h3>${e(a.category_label)}</h3>${priorityBadge(a)}</div><p>${e(a.classification_reason)}</p><p>${e(a.priority_reason)}</p><p>Подобрано инструкций: ${a.recommendations.length}.</p>`;}
  catch(err){$('#create-error').textContent=err.message;}finally{button.disabled=false;}
});
$('#incident-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=$('button[type=submit]',event.target);button.disabled=true;$('#create-error').textContent='';let saved=false;
  try{
    const result=await api('/api/incidents','POST',Object.fromEntries(new FormData(event.target)));saved=true;$('#create-dialog').close();
    await refresh();state.scope='open';state.selectedId=result.id;state.journalDetail=null;
    openDetail(result.id);
    toast('Обращение создано. Ниже — подходящая инструкция.');
  }catch(err){if(saved)toast('Обращение сохранено. Обновите страницу, чтобы загрузить журнал.');else $('#create-error').textContent=err.message;}finally{button.disabled=false;}
});
$('#article-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=$('button[type=submit]',event.target);button.disabled=true;$('#article-error').textContent='';let saved=false;
  const data=Object.fromEntries(new FormData(event.target));data.keywords=data.keywords.split(',').map(s=>s.trim()).filter(Boolean);data.steps=data.steps.split('\n').map(s=>s.trim()).filter(Boolean);
  try{await api('/api/articles','POST',data);saved=true;$('#article-dialog').close();await refresh();state.knowledge={search:'',category:''};render();toast('Инструкция добавлена в базу знаний');}
  catch(err){if(saved)toast('Инструкция сохранена. Обновите страницу для просмотра.');else $('#article-error').textContent=err.message;}finally{button.disabled=false;}
});
window.addEventListener('hashchange',()=>{requests.journal++;if(state.data)render();window.scrollTo({top:0,behavior:'instant'});});
const today=new Date();
$('#edition-date').textContent=new Intl.DateTimeFormat('ru-RU',{day:'numeric',month:'long',year:'numeric'}).format(today);
$('#edition-date').dateTime=`${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
refresh().then(render).catch(err=>{$('#main').innerHTML=`<div class="empty-state"><h2>Журнал недоступен</h2><p>${e(err.message)}</p><button class="button secondary" id="reload-button">Повторить загрузку</button></div>`;$('#reload-button').addEventListener('click',()=>location.reload());});
