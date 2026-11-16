import os,sys,tempfile,threading,json
from pathlib import Path
import fakeredis
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('JWT_SECRET','test-secret')
os.environ.setdefault('DATABASE_URL','sqlite:///'+tempfile.mkdtemp()+'/test.db')
os.environ.setdefault('REDIS_URL','redis://127.0.0.1:6399/0')
os.environ.setdefault('ARTIFACT_DIR',tempfile.mkdtemp())

@pytest.fixture(scope='session')
def redis_server():
 server=fakeredis.TcpFakeServer(('127.0.0.1',6399),server_type='redis')
 thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 yield server
 server.shutdown()

@pytest.fixture()
def client(redis_server):
 from fastapi.testclient import TestClient
 from src.main import app
 from src.config.database import Base,engine
 Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
 with TestClient(app) as c:yield c
