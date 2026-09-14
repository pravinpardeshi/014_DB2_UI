# import requests
# from requests.auth import HTTPBasicAuth
'''
Client ID: hoLvKpdJy29xs0AKootkCY1LhYayuU3l
App ID: 1543325e-fb41-4b4a-99f6-cbe85138397c
Secret Key: ATOArZpIwnDlxa4AcwQYsvk3VL3FCKw5g6QmWspPpS6mEh5LJ4rkL2-elymyKQYmVTCLF09D748C
'''

# JIRA_URL = "https://pravinpardeshi.atlassian.net/"
# EMAIL = "pravin.pardeshi.9806@gmail.com"
# API_TOKEN = "your_api_token"

# auth = HTTPBasicAuth(EMAIL, API_TOKEN)
# headers = {"Accept": "application/json", "Content-Type": "application/json"}

# Create ticket
# data = {
#     "fields": {
#         "project": {"key": "PROJ"},
#         "summary": "Test ticket created via Python",
#         "issuetype": {"name": "Task"}
#     }
# }

# r = requests.post(f"{JIRA_URL}/rest/api/3/issue", auth=auth, headers=headers, json=data)
# print(r.status_code, r.json())

# Update ticket
# issue_key = "PROJ-123"
# data = {"fields": {"summary": "Updated summary"}}

# r = requests.put(f"{JIRA_URL}/rest/api/3/issue/{issue_key}", auth=auth, headers=headers, json=data)
# print(r.status_code)


########################

import json
import os
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlencode, urlparse, parse_qs

import requests
# ============================================================
# CONFIGURATION
# ============================================================
CLIENT_ID = "hoLvKpdJy29xs0AKootkCY1LhYayuU3l"
APP_ID = "1543325e-fb41-4b4a-99f6-cbe85138397c"
CLIENT_SECRET = "ATOArZpIwnDlxa4AcwQYsvk3VL3FCKw5g6QmWspPpS6mEh5LJ4rkL2-elymyKQYmVTCLF09D748C"

# This MUST exactly match the callback URL configured
# in Atlassian Developer Console.
REDIRECT_URI = "http://localhost:8000/callback"

# Jira OAuth scopes.
# Make sure these are enabled in your Atlassian app.
SCOPES = [
    "read:jira-work",
    "write:jira-work",
    "offline_access",
]

AUTHORIZATION_URL = "https://auth.atlassian.com/authorize"
TOKEN_URL = "https://auth.atlassian.com/oauth/token"
RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"

TOKEN_FILE = "jira_token.json"


# ============================================================
# OAUTH CALLBACK SERVER
# ============================================================

authorization_code = None
oauth_error = None

class OAuthCallbackHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        global authorization_code
        global oauth_error

        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "error" in params:
            oauth_error = params["error"][0]

            self.send_response(400)
            self.end_headers()
            self.wfile.write(
                b"Authorization failed. You can close this browser window."
            )
            return

        if "code" in params:
            authorization_code = params["code"][0]

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()

            self.wfile.write(
                b"""
                <html>
                <body>
                    <h2>Jira authorization successful!</h2>
                    <p>You can close this browser window.</p>
                </body>
                </html>
                """
            )
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Authorization code not found.")

    def log_message(self, format, *args):
        # Keep the console output clean.
        pass


# ============================================================
# OAUTH AUTHENTICATION
# ============================================================

def authenticate():
    """
    Perform the Atlassian OAuth 2.0 authorization-code flow.
    Returns the access token.
    """

    global authorization_code
    global oauth_error

    authorization_code = None
    oauth_error = None

    # Generate OAuth state value for CSRF protection.
    state = secrets.token_urlsafe(32)

    params = {
        "audience": "api.atlassian.com",
        "client_id": CLIENT_ID,
        "scope": " ".join(SCOPES),
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "response_type": "code",
        "prompt": "consent",
    }

    authorization_url = (
        AUTHORIZATION_URL + "?" + urlencode(params)
    )

    print("\nOpening Atlassian authorization page...")
    print("\nIf the browser does not open automatically, use:")
    print(authorization_url)

    # Start local callback server.
    server = HTTPServer(
        ("localhost", 8000),
        OAuthCallbackHandler
    )

    # Open browser after server starts.
    threading.Timer(
        1.0,
        lambda: webbrowser.open(authorization_url)
    ).start()

    print("\nWaiting for Atlassian authorization...")

    # Wait for one callback.
    server.handle_request()

    if oauth_error:
        raise RuntimeError(
            f"Atlassian authorization failed: {oauth_error}"
        )

    if not authorization_code:
        raise RuntimeError(
            "No authorization code was received."
        )

    print("Authorization code received.")

    # Exchange authorization code for access token.
    response = requests.post(
        TOKEN_URL,
        headers={
            "Content-Type": "application/json"
        },
        json={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": authorization_code,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=30,
    )

    if response.status_code != 200:
        print(response.text)
        response.raise_for_status()

    token_data = response.json()

    save_token(token_data)

    print("Access token obtained.")

    return token_data["access_token"]


def save_token(token_data):
    """
    Save OAuth token information locally.
    """

    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f, indent=2)

    # Restrict permissions where supported.
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass


def load_token():
    """
    Load previously saved token.
    """

    if not os.path.exists(TOKEN_FILE):
        return None

    with open(TOKEN_FILE, "r") as f:
        return json.load(f)


def refresh_access_token(refresh_token):
    """
    Get a new access token using the refresh token.
    """

    response = requests.post(
        TOKEN_URL,
        headers={
            "Content-Type": "application/json"
        },
        json={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": refresh_token,
        },
        timeout=30,
    )

    if response.status_code != 200:
        print(response.text)
        response.raise_for_status()

    token_data = response.json()

    save_token(token_data)

    return token_data["access_token"]


def get_access_token():
    """
    Load an existing token if possible.
    Otherwise perform OAuth login.
    """

    token_data = load_token()

    if token_data:

        # If we have a refresh token, use it to get
        # a fresh access token.
        if "refresh_token" in token_data:
            try:
                return refresh_access_token(
                    token_data["refresh_token"]
                )
            except requests.HTTPError:
                print(
                    "Stored refresh token is no longer valid."
                )

    # No usable token. Start OAuth authorization.
    return authenticate()


# ============================================================
# JIRA CLOUD INFORMATION
# ============================================================

def get_jira_site(access_token):
    """
    Get Jira Cloud sites accessible by this OAuth token.

    Returns:
        {
            "cloud_id": "...",
            "jira_url": "...",
            "name": "..."
        }
    """

    response = requests.get(
        RESOURCES_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
        timeout=30,
    )

    if response.status_code != 200:
        print(response.text)
        response.raise_for_status()

    resources = response.json()

    if not resources:
        raise RuntimeError(
            "No Jira sites are accessible by this OAuth application."
        )

    # Find a Jira site.
    for resource in resources:

        scopes = resource.get("scopes", [])

        if any(
            scope.startswith("read:jira")
            or scope.startswith("write:jira")
            for scope in scopes
        ):
            return {
                "cloud_id": resource["id"],
                "jira_url": resource["url"],
                "name": resource["name"],
            }

    raise RuntimeError(
        "No Jira site was found in accessible resources."
    )


# ============================================================
# JIRA CLIENT
# ============================================================

class JiraClient:

    def __init__(self, access_token, cloud_id):
        self.access_token = access_token
        self.cloud_id = cloud_id

        self.base_url = (
            f"https://api.atlassian.com/ex/jira/"
            f"{cloud_id}/rest/api/3"
        )

        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    # --------------------------------------------------------
    # GET ISSUE
    # --------------------------------------------------------

    def get_issue(self, issue_key):
        """
        Retrieve a Jira issue.

        Example:
            issue = jira.get_issue("TEST-1")
        """

        url = f"{self.base_url}/issue/{issue_key}"

        response = requests.get(
            url,
            headers=self.headers,
            timeout=30,
        )

        if response.status_code != 200:
            print(response.text)
            response.raise_for_status()

        return response.json()

    # --------------------------------------------------------
    # CREATE ISSUE
    # --------------------------------------------------------

    def create_issue(
        self,
        project_key,
        summary,
        description,
        issue_type="Task",
    ):
        """
        Create a Jira issue.

        Example:

            issue = jira.create_issue(
                project_key="TEST",
                summary="My first API ticket",
                description="Created using Python"
            )
        """

        payload = {
            "fields": {
                "project": {
                    "key": project_key
                },
                "summary": summary,
                "issuetype": {
                    "name": issue_type
                },
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": description
                                }
                            ]
                        }
                    ]
                },
            }
        }

        url = f"{self.base_url}/issue"

        response = requests.post(
            url,
            headers=self.headers,
            json=payload,
            timeout=30,
        )

        if response.status_code != 201:
            print("Create issue failed:")
            print(response.text)
            response.raise_for_status()

        return response.json()

    # --------------------------------------------------------
    # UPDATE ISSUE
    # --------------------------------------------------------

    def update_issue(
        self,
        issue_key,
        summary=None,
        description=None,
    ):
        """
        Update an existing Jira issue.

        Example:

            jira.update_issue(
                "TEST-1",
                summary="Updated title"
            )
        """

        fields = {}

        if summary is not None:
            fields["summary"] = summary

        if description is not None:
            fields["description"] = {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": description
                            }
                        ]
                    }
                ]
            }

        if not fields:
            raise ValueError(
                "Nothing to update."
            )

        payload = {
            "fields": fields
        }

        url = f"{self.base_url}/issue/{issue_key}"

        response = requests.put(
            url,
            headers=self.headers,
            json=payload,
            timeout=30,
        )

        if response.status_code not in (200, 204):
            print("Update issue failed:")
            print(response.text)
            response.raise_for_status()

        return True

    def get_projects(self):
        """
        Retrieve Jira projects accessible to the authenticated user.
        """

        url = f"{self.base_url}/project"

        # response = requests.get( url, headers=self.headers, timeout=30,)
        response = requests.get( url, headers=self.headers, params={ "startAt": 0, "maxResults": 100, }, timeout=30,)

        if response.status_code != 200:
            print(response.text)
            response.raise_for_status()

        return response.json()

    def get_projects_new(self, project_key):
        url = f"{self.base_url}/project/{project_key}"

        response = requests.get( url, headers=self.headers, timeout=30,)

        print("Project status:", response.status_code)
        print(response.text)

        if response.status_code != 200:
            response.raise_for_status()

        return response.json()

    def get_permitted_projects(self):
        url = f"{self.base_url}/permissions/project"

        response = requests.post( url, headers=self.headers, json={ "permissions": [ "BROWSE_PROJECTS", "CREATE_ISSUES" ] }, timeout=30,)

        print("Permission status:", response.status_code)
        print(response.text)

        if response.status_code != 200:
            response.raise_for_status()

        return response.json()

    def update_description(self, issue_key, description):
        url = f"{self.base_url}/issue/{issue_key}"

        payload = {
            "fields": {
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": description
                                }
                            ]
                        }
                    ]
                }
            }
        }

        response = requests.put( url, headers=self.headers, json=payload, timeout=30,)

        if response.status_code not in (200, 204):
            print(response.text)
            response.raise_for_status()

        return True


    def get_description(self, issue_key):
        url = f"{self.base_url}/issue/{issue_key}"

        response = requests.get( url, headers=self.headers, params={ "fields": "description" }, timeout=30,)

        if response.status_code != 200:
            print(response.text)
            response.raise_for_status()

        return response.json()["fields"]["description"]


    def adf_to_text(self, adf):
        """
        Convert basic Jira ADF description to plain text.
        """

        if not adf:
            return ""

        result = []

    def walk(node):
        if isinstance(node, dict):

            if node.get("type") == "text":
                result.append(node.get("text", ""))

            for child in node.get("content", []):
                walk(child)

            # Add newline after paragraphs.
            if node.get("type") in (
                "paragraph",
                "heading",
                "blockquote",
            ):
                result.append("\n")

        elif isinstance(node, list):
            for item in node:
                walk(item)

        walk(adf)

        return "".join(result).strip()



# ============================================================
# MAIN
# ============================================================

def main():

    print("======================================")
    print(" Jira Python OAuth Client")
    print("======================================")

    # --------------------------------------------------------
    # 1. Authenticate
    # --------------------------------------------------------

    access_token = get_access_token()

    print("\nAuthentication successful.")

    # --------------------------------------------------------
    # 2. Find Jira Cloud site
    # --------------------------------------------------------

    site = get_jira_site(access_token)

    print("\nJira site:")
    print("Name:    ", site["name"])
    print("URL:     ", site["jira_url"])
    print("Cloud ID:", site["cloud_id"])

    # --------------------------------------------------------
    # 3. Create Jira client
    # --------------------------------------------------------

    jira = JiraClient(
        access_token=access_token,
        cloud_id=site["cloud_id"],
    )

    # --------------------------------------------------------
    # 3. Create Jira client
    # --------------------------------------------------------
    print("\nProjects you can access:")

    projects = jira.get_projects()

    for project in projects:
        # print( f"  Key: {project['key']:<15} " f"Name: {project['name']:<30}")
        print( f"  Key: {project['key']} " f"Name: {project['name']}")

    print("\n=== OAuth User ===")

    permitted = jira.get_permitted_projects()

    print("\nProjects where OAuth user has permissions:")

    for project in permitted.get("projects", []):
        print(
            f"ID={project['id']} | KEY={project['key']}"
        )

    # --------------------------------------------------------
    # 4. CHANGE THIS TO YOUR JIRA PROJECT KEY
    # --------------------------------------------------------

    PROJECT_KEY = "SCRUM"

    # --------------------------------------------------------
    # 5. CREATE TICKET
    # --------------------------------------------------------

    print("\nCreating Jira ticket...")

    created = jira.create_issue(
        project_key=PROJECT_KEY,
        summary="Ticket created from Python",
        description=( "This Jira ticket was created using the Jira Cloud REST API and OAuth 2.0."),
        issue_type="Task",
    )

    issue_key = created["key"]

    print("\nTicket created!")
    print("Issue key:", issue_key)
    print("Issue ID:", created["id"])

    # --------------------------------------------------------
    # 6. RETRIEVE TICKET
    # --------------------------------------------------------

    print("\nRetrieving ticket...")

    issue = jira.get_issue(issue_key)

    print("\nTicket information:")
    print("Key:", issue["key"])
    print("Summary:", issue["fields"]["summary"])
    print( "Status:", issue["fields"]["status"]["name"])
    print( "Description (before update):", issue["fields"]["description"])

    # --------------------------------------------------------
    # 7. UPDATE TICKET
    # --------------------------------------------------------

    print("\nUpdating ticket...")

    jira.update_issue(
        issue_key,
        summary="Ticket updated from Python",
        description=( "This description has been updated third time using the Jira REST API."),
    )

    print("Ticket updated successfully.")

    # --------------------------------------------------------
    # 8. Retrieve again
    # --------------------------------------------------------

    print("\nRetrieving updated ticket...")

    updated = jira.get_issue(issue_key)

    print("\nUpdated ticket:")
    print("Key:", updated["key"])
    print( "Summary:", updated["fields"]["summary"])
    print( "Description:", updated["fields"]["description"])


    # Convert to normal text
    # Update
    from datetime import datetime
    timestamp = datetime.now().strftime("%m%d%y-%H%M%S")

    jira.update_description( "SCRUM-1", f"This is the {timestamp} update.")

    adf_description = jira.get_description(f'{PROJECT_KEY}-1')
    description = adf_description['content'][0]['content'][0]['text']

    print(f"Description after update: {description}")
    print("\nDone!")

    print("\nRetrieving updated ticket...")

    updated = jira.get_issue(issue_key)

    print("\nUpdated ticket:")
    print("Key:", updated["key"])
    print( "Summary:", updated["fields"]["summary"])
    print( "Description:", updated["fields"]["description"])

if __name__ == "__main__":
    main()

