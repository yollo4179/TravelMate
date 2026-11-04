"""Check real Draft pins against supplied conditions; never invent road travel times."""
from __future__ import annotations
from datetime import datetime
import math
from typing import Any


def draft_checks(request: dict[str, Any], native: dict[str, Any]) -> dict[str, Any]:
    if native.get('type') != 'DRAFT':
        return {'status': 'not_ready' if native.get('type') == 'PLANNING_JOB' else 'not_applicable', 'checks': {},
                'route_time_verified': False, 'opening_hours_verified': False}
    draft = native.get('data')
    checks: dict[str, bool | None] = {}
    try:
        pins = draft['pins']
        ids = [pin['placeId'] for pin in pins]
        checks['unique_place_ids'] = bool(pins) and len(ids) == len(set(ids)) and all(type(identifier) is int and identifier > 0 for identifier in ids)
        checks['sequence'] = [pin['sequence'] for pin in pins] == list(range(1, len(pins) + 1))
        checks['positive_stay'] = all(type(pin['stayMinutes']) is int and pin['stayMinutes'] >= 10 for pin in pins)
        supplied = request.get('planningRequest')
        # A job lookup may not carry the creation request; absence is not a pass.
        context = supplied['context'] if supplied else None
        checks['required_places'] = all(stop['placeId'] in ids for stop in supplied['requiredStops']) if supplied else None
        if context:
            budget = (datetime.fromisoformat(context['endAt'].replace('Z','+00:00')) - datetime.fromisoformat(context['startAt'].replace('Z','+00:00'))).total_seconds() / 60
            checks['stay_within_window'] = sum(pin['stayMinutes'] for pin in pins) <= budget
            area = context['area']
            if area['type'] == 'CIRCLE':
                origin = area['center']
                def within(pin: dict[str, Any]) -> bool:
                    lat1,lat2 = map(math.radians,[origin['lat'],pin['latitude']])
                    dlon = math.radians(pin['longitude']-origin['lon'])
                    distance = 6371000 * 2 * math.asin(math.sqrt(min(1,math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2)))
                    return distance <= area['radiusMeters']
                checks['radius'] = all(within(pin) for pin in pins)
            else:
                checks['radius'] = None
            checks['category_requirements'] = None if context.get('categoryRequirements') else True
        else:
            checks.update(stay_within_window=None,radius=None,category_requirements=None)
    except (KeyError,TypeError,ValueError,OverflowError):
        checks['draft_contract'] = False
    return {'status':'failed' if False in checks.values() else 'not_assessed' if None in checks.values() else 'passed',
            'checks':checks,'route_time_verified':False,'opening_hours_verified':False}
