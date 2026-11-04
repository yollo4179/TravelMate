import copy
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracks.conversation.plan_checks import draft_checks
from common.dataset.io import read_json
from tracks.conversation.cases import DEFAULT_SUITE


class DraftChecksTests(unittest.TestCase):
    def setUp(self):
        self.request=next(case['api_request'] for case in read_json(DEFAULT_SUITE)['cases'] if case['case_id']=='CONV-PLAN-create')
        self.response={'type':'DRAFT','data':{'pins':[{'placeId':378,'sequence':1,'stayMinutes':60,'latitude':37.58,'longitude':126.99}]}}
    def test_queued_job_is_not_a_successful_plan(self):
        self.assertEqual(draft_checks(self.request,{'type':'PLANNING_JOB'})['status'],'not_ready')
    def test_valid_stay_and_radius_do_not_claim_optimized_travel_or_verified_hours(self):
        result=draft_checks(self.request,self.response)
        self.assertEqual(result['status'],'passed')
        self.assertFalse(result['route_time_verified'])
        self.assertFalse(result['opening_hours_verified'])
    def test_missing_required_place_overlong_stay_duplicate_and_outside_radius_fail(self):
        for patch in [{'placeId':999},{'stayMinutes':121},{'latitude':35.0}]:
            reply=copy.deepcopy(self.response);reply['data']['pins'][0].update(patch)
            self.assertEqual(draft_checks(self.request,reply)['status'],'failed')
        reply=copy.deepcopy(self.response);reply['data']['pins']*=2
        self.assertEqual(draft_checks(self.request,reply)['status'],'failed')
    def test_job_lookup_without_creation_conditions_is_unassessed(self):
        self.assertEqual(draft_checks({'planningRequest':None},self.response)['status'],'not_assessed')
