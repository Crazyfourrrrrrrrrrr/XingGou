"""Exercise missing-information and provider boundaries, without scene writes."""
import copy
import unittest
from core.workflow import guide, review

COMPLETE = dict(idea='四合院', gameType='单人展示', camera='第三人称', theme='安静院落',
                mechanics='从入口游览再返回，不做战斗', scope='单人，32×40米为初始方案')

class FakeProvider:
    def __init__(self, result):
        self.result = result
        self.calls = []
    def ask(self, system, data):
        self.calls.append((system, copy.deepcopy(data)))
        return self.result

class WorkflowTests(unittest.TestCase):
    def test_ai_plan_keeps_confirmed_brief_and_rejects_missing_before_provider(self):
        from core.generator import generate_plan, offline_plan
        p = FakeProvider(offline_plan('院落'))
        with self.assertRaises(ValueError): generate_plan('院落', 'ai', p, {'idea': '院落'})
        self.assertFalse(p.calls)
        result = generate_plan('院落', 'ai', p, COMPLETE)
        self.assertEqual(result['workflowBrief']['camera'], '第三人称')
        self.assertEqual(p.calls[0][1]['confirmedBrief']['mechanics'], COMPLETE['mechanics'])

    def test_questions_respect_known_answers_and_undecided_values(self):
        brief = dict(COMPLETE, camera='待定')
        before = copy.deepcopy(brief)
        state = guide(brief)
        self.assertFalse(state['readyForConcept'])
        self.assertEqual([q['field'] for q in state['missingQuestions']], ['camera'])
        self.assertEqual(brief, before)
        self.assertTrue(guide(COMPLETE, 'plan')['readyForConcept'])
        self.assertEqual(guide(COMPLETE, 'plan')['currentStage']['id'], 'plan')
        with self.assertRaises(ValueError): guide(COMPLETE, '../../server.py')
        with self.assertRaises(ValueError): guide(dict(COMPLETE, scope=12))
        with self.assertRaises(ValueError): guide(dict(COMPLETE, idea='a' * 3001))

    def test_offline_never_calls_provider_and_ai_cannot_approve_missing_brief(self):
        p = FakeProvider(dict(summary='可以搭了', questions=[], concepts=[], risks=[], readyForConcept=True))
        offline = review({'idea': '四合院'}, 'offline', p)
        self.assertFalse(p.calls)
        self.assertLessEqual(len(offline['questions']), 3)
        result = review({'idea': '四合院'}, 'ai', p)
        self.assertEqual(len(p.calls), 1)
        self.assertFalse(result['readyForConcept'])
        self.assertTrue(result['questions'])
        self.assertNotIn('nodes', result)
        self.assertNotIn('已创建', result['capabilityNote'])
        self.assertIn('当前接口只收到文字', p.calls[0][0])

    def test_ai_output_is_bounded_and_invalid_question_shape_rejected(self):
        p = FakeProvider(dict(summary='需求复述', questions=[{'field': 'unknown', 'question': '确认入口', 'reason': '动线'}], concepts=['围合'] * 10, risks=[]))
        result = review(COMPLETE, 'ai', p)
        self.assertEqual(result['questions'][0]['field'], 'idea')
        self.assertEqual(len(result['concepts']), 6)
        self.assertTrue(result['readyForConcept'])
        p.result = dict(questions=['bad'])
        with self.assertRaises(ValueError): review(COMPLETE, 'ai', p)

    def test_mcp_guide_is_available_without_a_running_editor(self):
        from mcp_server import dispatch
        import json
        result = dispatch(dict(method='tools/call', params=dict(name='level_design_guide', arguments=dict(brief={'idea': '四合院'}, stage='brief'))))
        state = json.loads(result['content'][0]['text'])
        self.assertFalse(state['readyForConcept'])
        self.assertIn('不要直接生成', dispatch({'method': 'initialize'})['instructions'])
        self.assertEqual(len(state['stages']), 9)

if __name__ == '__main__': unittest.main()
