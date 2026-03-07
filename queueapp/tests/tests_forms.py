from queueapp.forms import LoginForm, SignUpForm


def test_signup_form_validates_username_and_password(db):
    short_name_form = SignUpForm(data={"username": "abc", "password": "StrongPass123"})
    assert not short_name_form.is_valid()

    weak_password_form = SignUpForm(data={"username": "validname", "password": "123"})
    assert not weak_password_form.is_valid()

    valid_form = SignUpForm(data={"username": "validname", "password": "StrongPass123"})
    assert valid_form.is_valid()


def test_login_form_requires_both_fields():
    form = LoginForm(data={"username": "", "password": ""})
    assert not form.is_valid()

    form = LoginForm(data={"username": "alice", "password": "pass12345"})
    assert form.is_valid()
