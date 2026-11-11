/* Presentation only; all decisions and revisions are validated by the server. */
function investigationQuestion(q,extra=false) {
  const form=`<form class="investigation-answer" data-investigation-form data-operation="answer"><input type="hidden" name="question_id" value="${e(q.id)}"><span class="eyebrow">${extra?'Дополнительная проверка':'Следующая проверка'}</span><h3>${e(q.title)}</h3><p class="iv-how">${e(q.how)}</p><details class="iv-hint"><summary>Зачем эта проверка?</summary><p>${e(q.why)}</p></details><div class="iv-answers"><button class="button primary" type="submit" name="answer" value="yes">Да</button><button class="button secondary" type="submit" name="answer" value="no">Нет</button><button class="button secondary" type="submit" name="answer" value="unknown">Не удалось проверить</button></div><details class="iv-note"><summary>Добавить наблюдение</summary><label>Что удалось выяснить?<textarea name="note" rows="2" maxlength="1000" placeholder="Текст ошибки или результат проверки. Без паролей и секретов."></textarea></label></details></form>`;
  return extra?`<details class="iv-additional"><summary>Проверить оставшиеся версии</summary>${form}</details>`:form;
}
function scenarioOptions(inv,current) {return inv.scenarios.map(s=>`<option value="${e(s.id)}" ${s.id===current?'selected':''}>${e(s.title)}</option>`).join('');}
function investigationPanel(inv,i) {
  if(!inv)return '';
  if(!inv.started){
    if(inv.read_only)return '';
    return `<section class="investigation-panel" data-investigation><div class="iv-intro"><span class="eyebrow">Диагностический помощник</span><h2>Разобраться в причине</h2><p>Отмечайте результаты проверок. Система будет уточнять гипотезы и предлагать следующий шаг.</p></div><form class="iv-start" data-investigation-form data-operation="start"><label>Что исследуем?<select name="scenario" required aria-label="Сценарий расследования">${inv.suggested_scenario?'':'<option value="" selected>Выберите подходящий сценарий</option>'}${scenarioOptions(inv,inv.suggested_scenario)}</select></label><button class="button primary" type="submit">Начать расследование</button></form>${inv.suggested_scenario?'':'<p class="section-note">Для этой категории автоматический сценарий не выбран. Укажите подходящий вручную.</p>'}<p class="form-error" data-investigation-error role="alert"></p></section>`;
  }
  const supported=inv.hypotheses.filter(h=>h.status==='supported');
  const excluded=inv.hypotheses.filter(h=>h.status==='ruled_out').length;
  const readOnly=inv.read_only;
  const answerControls=!readOnly&&inv.next_question?investigationQuestion(inv.next_question,supported.length>0):'';
  const results=supported.map(h=>`<div class="iv-result"><h3>${e(h.title)}</h3><p class="iv-result-label">Наблюдения поддерживают эту версию</p><ul class="iv-evidence">${h.evidence.map(f=>`<li>${e(f.question)} — <b>${e(f.answer_label)}</b></li>`).join('')}</ul><h4>Что проверить и сделать дальше</h4><ol class="steps">${h.advice.map(s=>`<li>${e(s)}</li>`).join('')}</ol></div>`).join('');
  return `<section class="investigation-panel iv-active" data-investigation><div class="iv-top"><span class="eyebrow">Расследование / ${e(inv.scenario_title)}</span><span class="record-id">Проверок: ${inv.answered_count}</span></div>${readOnly?'<p class="iv-summary">Расследование сохранено. Для новых ответов верните обращение в работу.</p>':supported.length?'':`<p class="iv-summary">${e(inv.summary)}</p>`}${results}${answerControls}${!inv.next_question&&!supported.length?'<p class="section-note">Не выбирайте причину только методом исключения: для вывода нужны подтверждающие наблюдения.</p>':''}<div class="iv-hypotheses"><details><summary>Гипотезы · подтверждаются: ${supported.length}, исключены: ${excluded}</summary><div class="iv-hypothesis-list">${inv.hypotheses.map(h=>`<div class="iv-hypothesis ${e(h.status)}"><div><b>${e(h.title)}</b><span>${e(h.status_label)}</span></div><p>${h.contradictions.length?`Противоречит наблюдению: ${e(h.contradictions[0].question)} — ${e(h.contradictions[0].answer_label)}.`:h.evidence.length?`Совпавших наблюдений: ${h.evidence.length}.${h.status==='possible'?' Нужны дополнительные проверки.':''}`:'Подтверждающих наблюдений пока нет.'}</p></div>`).join('')}</div></details></div>
  ${inv.answers.length?`<details class="iv-history"><summary>Пройденные проверки (${inv.answers.length})</summary>${inv.answers.map((a,index)=>`<div class="iv-answer-record"><p><span class="record-id">${index+1}.</span> ${e(a.question)}</p><b>${e(a.answer_label)}</b>${a.note?`<p class="iv-observation">${e(a.note)}</p>`:''}${readOnly?'':`<details class="iv-revise"><summary>Исправить ответ</summary><p class="section-note">После исправления последующие ответы будут сняты, а ветка пересчитана. Прежние наблюдения останутся в истории обращения.</p><form data-investigation-form data-operation="revise"><input type="hidden" name="question_id" value="${e(a.question_id)}"><label>Результат проверки<select name="answer">${Object.entries({yes:'Да',no:'Нет',unknown:'Не удалось проверить'}).map(([key,label])=>`<option value="${key}" ${key===a.answer?'selected':''}>${label}</option>`).join('')}</select></label><label>Наблюдение<textarea name="note" rows="2" maxlength="1000">${e(a.note)}</textarea></label><button class="button secondary" type="submit">Сохранить исправление</button></form></details>`}</div>`).join('')}</details>`:''}
  ${readOnly?'':`<details class="iv-restart"><summary>Начать заново или сменить сценарий</summary><p class="section-note">Текущие ответы будут перенесены в историю обращения. Начнётся новое расследование.</p><form class="iv-start" data-investigation-form data-operation="restart"><label>Сценарий<select name="scenario" required>${scenarioOptions(inv,inv.scenario)}</select></label><button class="button secondary" type="submit">Начать заново</button></form></details>`}<p class="section-note">Вывод основан на ваших наблюдениях. После выполнения рекомендаций проверьте, восстановилась ли работа.</p><p class="form-error" data-investigation-error role="alert"></p></section>`;
}
const pendingInvestigations=new Set();
document.addEventListener('submit',async event=>{
  if(!event.target.matches('[data-investigation-form]'))return;
  event.preventDefault();
  const form=event.target,card=form.closest('[data-incident-card]'),id=Number(card.dataset.incidentCard);
  if(pendingInvestigations.has(id))return;
  const inv=state.journalDetail?.incident.id===id?state.journalDetail.investigation:null;
  if(!inv)return;
  const data=Object.fromEntries(new FormData(form));
  if(form.dataset.operation==='answer')data.answer=event.submitter?.value;
  data.action=form.dataset.operation;data.revision=inv.revision;
  const panel=form.closest('[data-investigation]'),error=$('[data-investigation-error]',panel);
  pendingInvestigations.add(id);error.textContent='';
  $$('button,select,textarea',panel).forEach(el=>el.disabled=true);
  let saved=false;
  try {
    await api(`/api/incidents/${id}/investigation`,'POST',data);saved=true;
    const result=await api(`/api/incidents/${id}`);
    if(state.page==='detail'&&state.selectedId===id){
      state.journalDetail=result;
      const container=$('#journal-detail');container.innerHTML=record(result);
      $('[data-investigation]',container)?.scrollIntoView({block:'start',behavior:'auto'});
      const active=$('.iv-result h3, .investigation-answer h3',container);
      if(active){active.setAttribute('tabindex','-1');active.focus({preventScroll:true});}
    }
    toast(data.action==='start'?'Расследование начато':data.action==='restart'?'Начато новое расследование':data.action==='revise'?'Ответ исправлен, ветка пересчитана':'Ответ сохранён, гипотезы обновлены');
  }catch(err){if(panel.isConnected)error.textContent=saved?'Ответ сохранён. Обновите страницу, чтобы увидеть результат.':err.message;else toast(err.message);}
  finally{pendingInvestigations.delete(id);$$('button,select,textarea',panel).forEach(el=>el.disabled=false);}
});
