from django import forms
from .models import Profile
from django.forms.widgets import ClearableFileInput
from .models import Submission

class CustomClearableFileInput(ClearableFileInput):
    initial_text = "الصورة الحالية"
    input_text = "تغيير"
    clear_checkbox_label = "إزالة الصورة"
    
class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['avatar']
        widgets = {
            'avatar': CustomClearableFileInput()
        }

    def clean_avatar(self):
        img = self.cleaned_data.get("avatar")
        if img and img.size > 3 * 1024 * 1024:  # 3 MB Limit
            raise forms.ValidationError("Bild darf max. 3 MB groß sein.")
        return img

class SubmissionForm(forms.ModelForm):
    class Meta:
        model = Submission
        fields = ["text"]
        widgets = {
            "text": forms.Textarea(attrs={"rows": 4, "class": "w-full border rounded p-2"})
        }
        labels = {
            "text": "النص",
        }
    
    def clean(self):
        cleaned = super().clean()
        text = (cleaned.get("text") or "").strip()
        if not text and not file:
            raise forms.ValidationError("يجب إدخال نص .")
        return cleaned
