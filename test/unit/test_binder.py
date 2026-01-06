import urllib
from app.config import settings


def test_post_happy_path(binder_vre, tmp_dir_setup):
    request_id = "abcd1234"
    local_git_url = f"https://{settings.host}/git/{request_id}"

    final_url = binder_vre.post(request_id)

    assert (
        final_url
        == f"{binder_vre.svc_url.rstrip("/")}/git/{urllib.parse.quote_plus(local_git_url)}/HEAD"
    )
