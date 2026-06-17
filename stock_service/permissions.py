from rest_framework.permissions import SAFE_METHODS, BasePermission


class AuthenticatedReadOnlyOrStaffWrite(BasePermission):
    """
    Allow authenticated users to read shared reference data,
    while restricting writes to staff users.
    """

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return bool(user.is_staff)
