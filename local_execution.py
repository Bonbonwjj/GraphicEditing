"""Opening this local application authorizes Python execution for team projects.

Compatibility helpers remain for existing render callers. Approval is application-wide
and survives project synchronization; it does not imply an operating-system sandbox.
"""


def trusted(project):
    return True


def approve(project):
    pass


def revoke_all():
    pass


def require_trust(project):
    pass
