import os
import shutil
import tempfile
from pathlib import Path

import pytest

# 必须在导入 app 之前设置：所有测试共用独立的内存库与假上游
os.environ["BAILIAN_API_KEY"] = "sk-test-key"
os.environ["BAILIAN_BASE_URL"] = "http://upstream.test/compatible-mode/v1"
os.environ["DATABASE_URL"] = "sqlite://"

# 配置目录指向真实 config 的临时副本：测试可以随意写 yaml，不污染项目文件
REPO_CONFIG = Path(__file__).resolve().parent.parent / "config"
CONFIG_TMP = Path(tempfile.mkdtemp(prefix="tokentool-test-config-"))
for _f in ("tiers.yaml", "free_models.yaml"):
    if (REPO_CONFIG / _f).exists():
        shutil.copy(REPO_CONFIG / _f, CONFIG_TMP / _f)
os.environ["CONFIG_DIR"] = str(CONFIG_TMP)
# .env 同样指向临时文件，防止测试改写真实 .env
ENV_TMP = Path(tempfile.mkdtemp(prefix="tokentool-test-env-")) / ".env"
ENV_TMP.write_text("BAILIAN_API_KEY=sk-from-envfile-1234567890\n", encoding="utf-8")
os.environ["ENV_PATH"] = str(ENV_TMP)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import CatalogLimit, CatalogModel, QuotaRule, UsageRecord  # noqa: E402


def make_client() -> TestClient:
    init_db()
    return TestClient(app)


@pytest.fixture  # type: ignore[name-defined]
def client():
    with make_client() as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_db():
    yield
    with SessionLocal() as db:
        for table in (UsageRecord, CatalogLimit, CatalogModel, QuotaRule):
            db.execute(delete(table))
        db.commit()
    # 配置文件也还原，避免用例间相互影响
    for _f in ("tiers.yaml", "free_models.yaml"):
        if (REPO_CONFIG / _f).exists():
            shutil.copy(REPO_CONFIG / _f, CONFIG_TMP / _f)
    ENV_TMP.write_text("BAILIAN_API_KEY=sk-from-envfile-1234567890\n", encoding="utf-8")
    from app.config import get_settings

    get_settings.cache_clear()  # 还原被 service 测试改写的 settings 缓存
