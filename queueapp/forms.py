from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.validators import MinLengthValidator, MaxLengthValidator
from django.utils.translation import gettext_lazy as _

from .models import Queue

class QueueForm(forms.ModelForm):
    class Meta:
        model = Queue
        fields = ['name']


class SignUpForm(forms.ModelForm):
    password = forms.CharField(
        label=_("Password"),
        widget=forms.PasswordInput,
        min_length=8,
    )
    username = forms.CharField(
        label=_("Username"),
        min_length=4,
        max_length=31,
        validators=[
            MinLengthValidator(4, message=_("Username must be at least 4 characters.")),
            MaxLengthValidator(31, message=_("Username must be at most 31 characters.")),
        ],
    )

    class Meta:
        model = User
        fields = ["username", "password"]

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password)
        return password

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class LoginForm(forms.Form):
    username = forms.CharField(label=_("Username"))
    password = forms.CharField(label=_("Password"), widget=forms.PasswordInput)


class AddInfoForm(forms.Form):
    info = forms.CharField(max_length=64, required=False, label=_("Note"))
