"""실제 API 없이 호출 상한·재시도 차단·모델 불일치·진단 비밀 제거를 검사한다."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT.parent)]
from app.contextual.artifacts import collect_bundle
from app.enrichment.agent import AgentSettings
from Evaluation.tracks.contextual.v7_generation import prepare,execute
from test_contextual_chunks import bundle,response_for


class V7ExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def plan(self,root: Path) -> tuple[Path,Path,str]:
        value=bundle()
        raw=response_for(value)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=raw))) as client:
            baseline=await collect_bundle(value,AgentSettings(model='perplexity/sonar',api_key='mock-only'),root/'baseline',client)
        plan=prepare(baseline,root/'candidate')
        secret='pplx-'+'x'*32
        key=root/'mock-key.txt';key.write_text(secret,encoding='utf-8')
        return plan,key,secret

    @staticmethod
    def response(request: httpx.Request, *, model: str = 'perplexity/sonar') -> httpx.Response:
        spans=json.loads(json.loads(request.content)['input'])['spans']
        rows=[{**{key:span[key] for key in ('source_id','start','end')},'context_text':'합성 미귀속 원문',
               'place_refs':[],'entities':[],'hypothetical_questions':[],'content_kind':'other','relations':[]} for span in spans]
        return httpx.Response(200,json={'id':'mock-response','status':'completed','model':model,
            'usage':{'cost':{'currency':'USD','total_cost':0}},'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'chunks':rows})}]}]})

    async def test_two_calls_preserve_inputs_and_reexecution_opens_no_client(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);plan,key,_=await self.plan(root)
            original=plan.read_bytes();calls=[]
            def send(request: httpx.Request) -> httpx.Response:
                calls.append(request)
                return self.response(request)
            result=await execute(plan,key,transport=httpx.MockTransport(send))
            report=json.loads(result.read_text(encoding='utf-8'))
            self.assertTrue(report['all_collected']);self.assertEqual(len(calls),2)
            self.assertEqual(report['api_calls'],2);self.assertEqual(plan.read_bytes(),original)
            with patch('httpx.AsyncClient',side_effect=AssertionError('재실행 HTTP 금지')):
                with self.assertRaisesRegex(ValueError,'자동 재시도'):
                    await execute(plan,key)

    async def test_model_mismatch_stops_after_one_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan,key,_=await self.plan(Path(directory))
            result=await execute(plan,key,transport=httpx.MockTransport(lambda request:self.response(request,model='other-model')))
            report=json.loads(result.read_text(encoding='utf-8'))
            self.assertFalse(report['all_collected']);self.assertEqual(report['api_calls'],1)

    async def test_http_error_is_redacted_and_is_never_retried(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan,key,secret=await self.plan(Path(directory))
            result=await execute(plan,key,transport=httpx.MockTransport(lambda _:httpx.Response(403,text='blocked '+secret)))
            report=json.loads(result.read_text(encoding='utf-8'))
            self.assertFalse(report['all_collected']);self.assertEqual(report['api_calls'],1)
            errors=list((plan.parent/'http-errors').glob('*.json'));self.assertEqual(len(errors),1)
            diagnostic=errors[0].read_text(encoding='utf-8')
            self.assertNotIn(secret,diagnostic);self.assertIn('[REDACTED]',diagnostic)


if __name__=='__main__':
    unittest.main()
