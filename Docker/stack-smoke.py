"""Functional smoke checks for the local Docker stack; never prints tokens/vectors."""
import json
import math
import os
import secrets
import subprocess
import urllib.request
import uuid

server = f"http://127.0.0.1:{os.environ.get('SERVER_PORT', '8080')}"
embedding = f"http://127.0.0.1:{os.environ.get('EMBEDDING_PORT', '8000')}"


def request(base, path, body=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(base + path,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=120) as response:
        assert response.status == 200
        return response.read().decode()


def validate_vectors(vectors, count):
    assert len(vectors) == count
    for vector in vectors:
        assert len(vector) == 1024 and all(math.isfinite(x) for x in vector)
        assert abs(math.sqrt(sum(x * x for x in vector)) - 1.0) < 0.001


docs = json.loads(request(server, '/v3/api-docs'))
assert '/api/users/me' in docs['paths']
health = json.loads(request(embedding, '/health'))
assert health == {'status': 'ok', 'dim': 1024}
texts = ['경주에서 문화유산을 둘러보는 여행', '경주 역사 유적과 문화재 관광', '컴퓨터 프로그래밍 언어의 함수 문법']
vectors = json.loads(request(embedding, '/embed', {'texts': texts}))['embeddings']
validate_vectors(vectors, 3)
related = sum(a * b for a, b in zip(vectors[0], vectors[1]))
unrelated = sum(a * b for a, b in zip(vectors[0], vectors[2]))
assert related > unrelated, 'Semantic smoke failed: related pair should outrank unrelated pair'
print('PASS: FastAPI health, real BGE-M3 inference, 3x1024 finite normalized vectors, semantic smoke')

# Exercise Docker service DNS and routing from inside the Spring container.
result = subprocess.run([
    'docker', 'exec', 'travelmate-server', 'curl', '--fail', '--silent', '--max-time', '120',
    '-H', 'Content-Type: application/json', '-d', json.dumps({'texts': ['서울 문화유산 여행']}),
    'http://embedding:8000/embed',
], check=True, capture_output=True, text=True)
validate_vectors(json.loads(result.stdout)['embeddings'], 1)
print('PASS: Spring container -> embedding service DNS -> real inference')

user_id = 'docker_smoke_' + uuid.uuid4().hex
password = secrets.token_urlsafe(24)
try:
    request(server, '/api/users/signup', {'userId': user_id, 'email': user_id + '@example.invalid',
                                        'password': password, 'nickname': user_id})
    login = json.loads(request(server, '/api/auth/login', {'userId': user_id, 'password': password}))
    assert login['accessToken'] and login['uid']
    profile = json.loads(request(server, '/api/users/me', token=login['accessToken']))
    assert profile['email'] == user_id + '@example.invalid'
    request(server, '/api/auth/logout', {}, token=login['accessToken'])
    print('PASS: containerized Spring signup, login/Redis, JWT profile and logout')
finally:
    # user_id contains only the fixed prefix and UUID hex; remove only this test's row.
    subprocess.run(['docker', 'exec', 'travel-postgres', 'psql', '-v', 'ON_ERROR_STOP=1',
                    '-U', 'ssafy', '-d', 'travel_db', '-c',
                    f"DELETE FROM users WHERE user_id='{user_id}';"],
                   check=True, stdout=subprocess.DEVNULL)
