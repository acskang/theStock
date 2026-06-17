from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import UserProfile


class LocalAccountAuthViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.User = get_user_model()

    def test_signup_creates_local_user_and_logs_in(self):
        response = self.client.post(
            reverse("signup"),
            {
                "username": "new_user",
                "full_name": "New User",
                "smartphone_number": "010-1234-5678",
                "password": "Password123!",
                "password_confirm": "Password123!",
            },
        )

        self.assertRedirects(response, reverse("consulting_holding_list"), fetch_redirect_response=False)
        user = self.User.objects.get(username="new_user")
        self.assertEqual(user.email, "")
        self.assertEqual(UserProfile.objects.get(user=user).smartphone_number, "01012345678")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.id)
        self.assertEqual(response.cookies[settings.THEPEACH_SSO_ACCESS_COOKIE_NAME].value, "")
        self.assertEqual(response.cookies[settings.THEPEACH_SSO_REFRESH_COOKIE_NAME].value, "")

    def test_signup_requires_smartphone_number(self):
        response = self.client.post(
            reverse("signup"),
            {
                "username": "new_user",
                "full_name": "New User",
                "password": "Password123!",
                "password_confirm": "Password123!",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "필수 항목입니다.")
        self.assertFalse(self.User.objects.filter(username="new_user").exists())

    def test_signup_rejects_invalid_smartphone_number(self):
        response = self.client.post(
            reverse("signup"),
            {
                "username": "new_user",
                "full_name": "New User",
                "smartphone_number": "02-123-4567",
                "password": "Password123!",
                "password_confirm": "Password123!",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "스마트폰 번호를 정확히 입력해주세요.")
        self.assertFalse(self.User.objects.filter(username="new_user").exists())

    def test_signup_rejects_duplicate_username(self):
        self.User.objects.create_user(username="stock_user", password="Password123!")

        response = self.client.post(
            reverse("signup"),
            {
                "username": "stock_user",
                "full_name": "User Example",
                "smartphone_number": "01012345678",
                "password": "Password123!",
                "password_confirm": "Password123!",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "이미 사용 중인 사용자 이름입니다.")
        self.assertEqual(self.User.objects.filter(username="stock_user").count(), 1)

    def test_login_uses_local_user(self):
        user = self.User.objects.create_user(username="stock_user", password="Password123!")

        response = self.client.post(
            reverse("login"),
            {"username": "stock_user", "password": "Password123!"},
        )

        self.assertRedirects(response, reverse("consulting_holding_list"), fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.id)
        self.assertEqual(response.cookies[settings.THEPEACH_SSO_ACCESS_COOKIE_NAME].value, "")
        self.assertEqual(response.cookies[settings.THEPEACH_SSO_REFRESH_COOKIE_NAME].value, "")

    def test_login_failure_renders_error(self):
        response = self.client.post(
            reverse("login"),
            {"username": "missing_user", "password": "Password123!"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "사용자 이름 또는 비밀번호를 확인해주세요.")
        self.assertNotContains(response, "Peach SSO")

    def test_logout_clears_local_session_and_old_sso_cookies(self):
        user = self.User.objects.create_user(username="local-user", email="local@example.com", password="pw123456")
        self.client.force_login(user)
        session = self.client.session
        session["thepeach_access_token"] = "access-token"
        session["thepeach_refresh_token"] = "refresh-token"
        session["thepeach_auth_source"] = "thepeach_sso"
        session.save()

        response = self.client.post(reverse("logout"))

        self.assertRedirects(response, reverse("dashboard"))
        self.assertNotIn("thepeach_access_token", self.client.session)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(response.cookies[settings.THEPEACH_SSO_ACCESS_COOKIE_NAME].value, "")
        self.assertEqual(response.cookies[settings.THEPEACH_SSO_REFRESH_COOKIE_NAME].value, "")

    def test_old_shared_sso_cookie_does_not_authenticate_user(self):
        self.client.cookies[settings.THEPEACH_SSO_ACCESS_COOKIE_NAME] = "shared-access"
        self.client.cookies[settings.THEPEACH_SSO_REFRESH_COOKIE_NAME] = "shared-refresh"

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)
