"""Minimal Moodle web-service (REST) client."""
import requests

from .config import SITE


class MoodleError(Exception):
    pass


class InvalidToken(MoodleError):
    pass


def _flatten(prefix, value, out):
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}[{k}]" if prefix else k, v, out)
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _flatten(f"{prefix}[{i}]", v, out)
    elif isinstance(value, bool):
        out[prefix] = int(value)
    else:
        out[prefix] = value


class MoodleClient:
    def __init__(self, token: str):
        self.token = token
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "EPFL-Moodle-Downloader/1.0"

    def call(self, function: str, **params):
        data = {"wstoken": self.token, "wsfunction": function, "moodlewsrestformat": "json"}
        _flatten("", params, data)
        r = self.session.post(f"{SITE}/webservice/rest/server.php", data=data, timeout=60)
        r.raise_for_status()
        result = r.json()
        if isinstance(result, dict) and result.get("exception"):
            if result.get("errorcode") in ("invalidtoken", "accessexception"):
                raise InvalidToken(result.get("message", "invalid token"))
            raise MoodleError(f"{function}: {result.get('message')}")
        return result

    def site_info(self):
        return self.call("core_webservice_get_site_info")

    def courses(self, userid: int):
        return self.call("core_enrol_get_users_courses", userid=userid)

    def course_contents(self, courseid: int):
        return self.call("core_course_get_contents", courseid=courseid)

    def assignments(self, courseid: int) -> dict:
        """cmid -> assignment, for intro attachments that course contents omit."""
        try:
            data = self.call("mod_assign_get_assignments", courseids=[courseid])
        except MoodleError:
            return {}
        out = {}
        for c in data.get("courses", []):
            for a in c.get("assignments", []):
                out[a.get("cmid")] = a
        return out

    def file_url(self, url: str) -> str:
        """Turn any Moodle file link into one this token can download."""
        if "/webservice/pluginfile.php" not in url and "/pluginfile.php" in url:
            url = url.replace("/pluginfile.php", "/webservice/pluginfile.php", 1)
        if "token=" not in url:
            url += ("&" if "?" in url else "?") + f"token={self.token}"
        return url
