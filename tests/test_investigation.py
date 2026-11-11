import unittest
from concurrent.futures import ThreadPoolExecutor

import test_app
from investigation import derive, SCENARIOS
from database import connect, initialize


def facts(**values):
    return [dict(question_id=key, answer=value, note="", answered_at="2026-11-12T09:00:00+00:00") for key, value in values.items()]


class InferenceTests(unittest.TestCase):
    def test_same_description_different_evidence_different_results(self):
        blocked = derive("access", facts(other_login="yes", account_blocked="yes"))
        outage = derive("access", facts(other_login="no", auth_health="no"))
        self.assertEqual([h['id'] for h in blocked['hypotheses'] if h['status']=='supported'], ['locked'])
        self.assertEqual([h['id'] for h in outage['hypotheses'] if h['status']=='supported'], ['auth_failure'])

    def test_next_check_depends_on_answer(self):
        self.assertEqual(derive('access', facts(other_login='yes'))['next_question']['id'], 'account_blocked')
        self.assertEqual(derive('access', facts(other_login='no'))['next_question']['id'], 'auth_health')

    def test_credentials_require_both_observations(self):
        result = derive('access', facts(credential_error='yes'))
        self.assertFalse(any(h['status']=='supported' for h in result['hypotheses']))
        result = derive('access', facts(account_blocked='no', credential_error='yes'))
        self.assertEqual(next(h for h in result['hypotheses'] if h['id']=='credentials')['status'], 'supported')

    def test_elimination_is_not_confirmation(self):
        result = derive('access', facts(other_login='yes', account_blocked='no', credential_error='no'))
        self.assertEqual(result['phase'], 'inconclusive')
        self.assertIsNone(result['next_question'])
        self.assertTrue(all(h['status']=='ruled_out' for h in result['hypotheses']))

    def test_unknown_does_not_exclude_or_confirm(self):
        for key, spec in SCENARIOS.items():
            result = derive(key, facts(**{q['id']:'unknown' for q in spec['questions']}))
            self.assertEqual(result['phase'], 'inconclusive')
            self.assertTrue(all(h['status']=='possible' for h in result['hypotheses']))
            self.assertEqual(result['unknown_count'],len(spec['questions']))

    def test_database_network_and_authentication_are_distinct(self):
        network = derive('database', facts(db_running='yes', db_port='no'))
        auth = derive('database', facts(db_running='yes', db_port='yes', db_auth_error='yes'))
        self.assertEqual([h['id'] for h in network['hypotheses'] if h['status']=='supported'], ['network'])
        self.assertEqual([h['id'] for h in auth['hypotheses'] if h['status']=='supported'], ['db_credentials'])

    def test_dns_needs_successful_direct_access(self):
        result=derive('application', facts(service_running='yes', db_error='no', direct_access='yes', dns_resolves='no'))
        self.assertEqual([h['id'] for h in result['hypotheses'] if h['status']=='supported'], ['dns'])

    def test_each_supported_hypothesis_has_evidence_and_advice(self):
        for key,spec in SCENARIOS.items():
            for item in spec['hypotheses']:
                result=derive(key,facts(**item['conditions']))
                selected=next(h for h in result['hypotheses'] if h['id']==item['id'])
                self.assertEqual(selected['status'],'supported')
                self.assertEqual(len(selected['evidence']),len(item['conditions']))
                self.assertTrue(selected['advice'])


class InvestigationAPITests(unittest.TestCase):
    setUp = test_app.APITests.setUp
    tearDown = test_app.APITests.tearDown
    request = test_app.APITests.request
    payload = test_app.APITests.payload
    def make_case(self):
        result=self.request('/api/incidents','POST',self.payload())[1]
        self.case_id=result['id']
        self.case_path=f'/api/incidents/{self.case_id}'
        self.endpoint=self.case_path+'/investigation'

    def current(self):
        return self.request(self.case_path)[1]['investigation']

    def command(self, action, **values):
        return self.request(self.endpoint,'POST',dict(action=action,revision=self.current()['revision'],**values))

    def test_session_persists_across_initialization(self):
        self.make_case()
        self.assertFalse(self.current()['started'])
        self.assertEqual(self.command('start',scenario='access')[0],200)
        self.command('answer',question_id='other_login',answer='yes')
        initialize(self.path)
        result=self.current()
        self.assertEqual(result['answered_count'],1)
        self.assertEqual(result['next_question']['id'],'account_blocked')
        self.assertEqual(result['revision'],2)

    def test_revise_recalculates_and_preserves_old_evidence_in_history(self):
        self.make_case();self.command('start',scenario='access')
        self.command('answer',question_id='other_login',answer='yes',note='Контрольный вход успешен')
        self.command('answer',question_id='account_blocked',answer='yes')
        self.assertEqual(self.current()['phase'],'supported')
        code,result=self.command('revise',question_id='other_login',answer='no')
        self.assertEqual(code,200)
        self.assertEqual(result['investigation']['answered_count'],1)
        self.assertEqual(result['investigation']['next_question']['id'],'auth_health')
        self.assertFalse(any(h['status']=='supported' for h in self.current()['hypotheses']))
        events=self.request(self.case_path)[1]['events']
        self.assertTrue(any('Контрольный вход успешен' in ev['text'] for ev in events))
        self.assertIn('account_blocked',events[-1]['text'])

    def test_invalid_actions_never_change_revision(self):
        self.make_case();self.command('start',scenario='access')
        for payload in [dict(action='answer',question_id='wrong',answer='yes'),dict(action='answer',question_id='other_login',answer=[]),dict(action='answer',question_id='other_login',answer='yes',note='x'*1001),dict(action='revise',question_id='wrong',answer='yes'),dict(action='start',scenario='access')]:
            self.assertIn(self.request(self.endpoint,'POST',dict(revision=1,**payload))[0],(400,409))
        self.assertEqual(self.current()['revision'],1)
        self.assertEqual(self.current()['answered_count'],0)
        self.assertEqual(self.request(self.endpoint,'POST',dict(action='answer',revision=True,question_id='other_login',answer='yes'))[0],400)

    def test_stale_and_concurrent_answers_are_rejected(self):
        self.make_case();self.command('start',scenario='access')
        body=dict(action='answer',revision=1,question_id='other_login',answer='yes')
        with ThreadPoolExecutor(max_workers=2) as pool:
            codes=list(pool.map(lambda _:self.request(self.endpoint,'POST',body)[0],range(2)))
        self.assertEqual(sorted(codes),[200,409])
        self.assertEqual(self.current()['answered_count'],1)

    def test_closed_case_is_read_only_and_reopens_with_history(self):
        self.make_case();self.command('start',scenario='access')
        self.command('answer',question_id='other_login',answer='unknown')
        self.request(self.case_path,'PATCH',dict(status='in_progress'))
        self.request(self.case_path,'PATCH',dict(status='resolved',resolution='Выполнена контрольная проверка доступа'))
        self.assertTrue(self.current()['read_only'])
        self.assertEqual(self.command('answer',question_id='account_blocked',answer='no')[0],409)
        self.request(self.case_path,'PATCH',dict(status='in_progress'))
        self.assertFalse(self.current()['read_only'])
        self.assertEqual(self.current()['answered_count'],1)

    def test_restart_switches_scenario_and_archives_answers(self):
        self.make_case();self.command('start',scenario='access')
        self.command('answer',question_id='other_login',answer='unknown',note='Нет контрольной записи')
        self.assertEqual(self.command('restart',scenario='database')[0],200)
        self.assertEqual(self.current()['scenario'],'database')
        self.assertEqual(self.current()['answered_count'],0)
        self.assertIn('Нет контрольной записи',self.request(self.case_path)[1]['events'][-1]['text'])

    def test_old_database_migration_does_not_overwrite_incidents(self):
        self.make_case()
        with connect(self.path) as db:
            db.execute('DROP TABLE investigations')
        initialize(self.path)
        self.assertFalse(self.current()['started'])
        self.assertEqual(len(self.request('/api/bootstrap')[1]['incidents']),1)


if __name__=='__main__':
    unittest.main()
