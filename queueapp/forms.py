from django import forms
from .models import Queue
from django.contrib.auth.models import User
from django.core.validators import MinLengthValidator, MaxLengthValidator

class QueueForm(forms.ModelForm):
    class Meta:
        model = Queue
        fields = ['name']


class SignUpForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput)
    username = forms.CharField(
        label="Username",
        min_length=3,
        max_length=31,
        validators=[
            MinLengthValidator(4, message="Username must be at least 3 characters."),
            MaxLengthValidator(31, message="Username must be at most 31 characters.")
        ]
    )

    class Meta:
        model = User
        fields = ['username', 'password']

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
        return user


class LoginForm(forms.Form):
    username = forms.CharField()
    password = forms.CharField(widget=forms.PasswordInput)


class AddInfoForm(forms.Form):
    info = forms.CharField(max_length=64, required=False)

