from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.db.models import Q
from django.utils import timezone

from .models import Drug, Elder, MedicationSchedule, Reminder, UserProfile
from .slots import SLOT_CHOICES, period_for_slot

INPUT = "w-full px-4 py-2.5 rounded-lg border border-slate-300 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-brand"
CHECKBOX = "h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand"
SLOT_SELECT_CHOICES = list(SLOT_CHOICES)
OPTIONAL_SLOT_SELECT_CHOICES = [("", "未指定")] + SLOT_SELECT_CHOICES
User = get_user_model()


class AccountRegistrationForm(UserCreationForm):
    email = forms.EmailField(
        label="電子信箱",
        widget=forms.EmailInput(
            attrs={"class": INPUT, "autocomplete": "email", "placeholder": "用於忘記密碼時重設"}
        ),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("這個信箱已被使用。")
        return email


class ReminderForm(forms.ModelForm):
    elder = forms.ModelChoiceField(
        label="照護對象",
        queryset=Elder.objects.none(),
        widget=forms.Select(attrs={"class": INPUT}),
        help_text="選擇實際服藥者；系統會保留姓名與年齡快照。",
    )
    slot = forms.TypedChoiceField(
        label="藥盒時段",
        choices=OPTIONAL_SLOT_SELECT_CHOICES,
        coerce=int,
        empty_value=None,
        required=False,
        widget=forms.Select(attrs={"class": INPUT}),
    )
    scheduled_datetime = forms.DateTimeField(
        label="服藥日期時間",
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "class": INPUT}, format="%Y-%m-%dT%H:%M"),
    )

    class Meta:
        model = Reminder
        fields = [
            "medicine_name",
            "scheduled_datetime",
            "dose_count",
            "reminder_hint",
            "slot",
            "device_id",
        ]
        widgets = {
            "medicine_name": forms.TextInput(attrs={"class": INPUT, "placeholder": "例如：降血壓藥"}),
            "dose_count": forms.TextInput(attrs={"class": INPUT, "placeholder": "例如：1"}),
            "reminder_hint": forms.TextInput(attrs={"class": INPUT}),
            "slot": forms.Select(attrs={"class": INPUT}),
            "device_id": forms.TextInput(attrs={"class": INPUT, "placeholder": "pillbox-01"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and user.is_authenticated:
            elders = Elder.objects.filter(owner=user)
            self.fields["elder"].queryset = elders
            if self.instance and self.instance.pk:
                self.fields["elder"].initial = elders.filter(name=self.instance.user_name).first()
        if self.instance and self.instance.pk:
            self.fields["elder"].required = False
        self.fields["device_id"].required = False
        self.fields["device_id"].help_text = "選填；留空時會優先使用照護對象已綁定的智慧藥盒。"

    def clean_medicine_name(self):
        value = self.cleaned_data.get("medicine_name", "").strip()
        if not value:
            raise forms.ValidationError("藥品名稱不得為空。")
        return value

    def clean_scheduled_datetime(self):
        value = self.cleaned_data.get("scheduled_datetime")
        if value is None:
            raise forms.ValidationError("請選擇服藥日期時間。")
        if not self.instance.pk and value < timezone.now():
            raise forms.ValidationError("新增任務的服藥日期時間不能是過去。")
        return value


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ["android_name"]
        labels = {"android_name": "此帳號要接收的 Android 使用者姓名"}
        widgets = {
            "android_name": forms.Textarea(
                attrs={
                    "class": INPUT,
                    "placeholder": "例如：王阿公、媽媽、小明\n可用逗號、頓號或換行分隔",
                    "rows": 4,
                }
            )
        }
        help_texts = {
            "android_name": "Android 上傳的 user_name 符合其中一個名字時，紀錄會自動歸到此帳號。"
        }

    def clean_android_name(self):
        value = self.cleaned_data.get("android_name", "").strip()
        if not value:
            raise forms.ValidationError("請至少輸入一個 Android 使用者姓名。")
        return value

class ElderForm(forms.ModelForm):
    class Meta:
        model = Elder
        fields = ["name", "age", "notes"]
        widgets = {
            "name": forms.TextInput(attrs={"class": INPUT}),
            "age": forms.NumberInput(attrs={"class": INPUT, "min": 1, "max": 120}),
            "notes": forms.Textarea(attrs={"class": INPUT, "rows": 3}),
        }


class DrugForm(forms.ModelForm):
    class Meta:
        model = Drug
        fields = ["name_zh", "generic_name", "fda_product_ndc", "dosage_note"]
        widgets = {
            "name_zh": forms.TextInput(attrs={"class": INPUT, "placeholder": "網站顯示名稱"}),
            "generic_name": forms.TextInput(attrs={"class": INPUT, "placeholder": "例如 acetaminophen"}),
            "fda_product_ndc": forms.TextInput(attrs={"class": INPUT}),
            "dosage_note": forms.Textarea(attrs={"class": INPUT, "rows": 3}),
        }
        help_texts = {
            "generic_name": "QA Agent 會優先用這個英文學名搜尋已同步的 FDA 文件。",
            "fda_product_ndc": "可填入藥品包裝或來源資料上的 NDC。",
        }


class MedicationScheduleForm(forms.ModelForm):
    slot = forms.TypedChoiceField(
        label="藥盒時段",
        choices=SLOT_SELECT_CHOICES,
        coerce=int,
        initial=1,
        widget=forms.Select(attrs={"class": INPUT}),
    )
    drug_name = forms.CharField(
        label="藥品名稱",
        max_length=180,
        widget=forms.TextInput(
            attrs={
                "class": INPUT,
                "placeholder": "輸入藥名，例如：降血壓藥、metformin",
                "list": "drugOptions",
                "autocomplete": "off",
            }
        ),
        help_text="輸入關鍵字即可；不用從上萬筆資料慢慢下拉找。若找不到會建立本地藥名。",
    )
    weekdays = forms.MultipleChoiceField(
        label="執行星期",
        choices=[
            ("1", "週一"),
            ("2", "週二"),
            ("3", "週三"),
            ("4", "週四"),
            ("5", "週五"),
            ("6", "週六"),
            ("7", "週日"),
        ],
        widget=forms.CheckboxSelectMultiple(attrs={"class": CHECKBOX}),
        help_text="可複選固定排程執行日。",
    )

    class Meta:
        model = MedicationSchedule
        fields = [
            "elder",
            "drug_name",
            "slot",
            "scheduled_time",
            "dose_count",
            "reminder_hint",
            "weekdays",
            "grace_minutes",
            "missed_after_minutes",
            "device_id",
            "is_active",
        ]
        widgets = {
            "elder": forms.Select(attrs={"class": INPUT}),
            "slot": forms.Select(attrs={"class": INPUT}),
            "scheduled_time": forms.TimeInput(attrs={"class": INPUT, "type": "time"}),
            "dose_count": forms.TextInput(attrs={"class": INPUT}),
            "reminder_hint": forms.TextInput(attrs={"class": INPUT}),
            "grace_minutes": forms.NumberInput(attrs={"class": INPUT, "min": 1, "max": 180}),
            "missed_after_minutes": forms.NumberInput(attrs={"class": INPUT, "min": 2, "max": 1440}),
            "device_id": forms.TextInput(attrs={"class": INPUT}),
            "is_active": forms.CheckboxInput(attrs={"class": CHECKBOX}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and user.is_authenticated:
            self.fields["elder"].queryset = Elder.objects.filter(owner=user)
        else:
            self.fields["elder"].queryset = Elder.objects.none()
        if self.instance and self.instance.pk and self.instance.drug_id:
            self.fields["drug_name"].initial = self.instance.drug.name_zh or self.instance.drug.generic_name
        if self.instance and self.instance.pk:
            self.fields["weekdays"].initial = [
                value.strip() for value in self.instance.weekdays.split(",") if value.strip()
            ]

    def clean_weekdays(self):
        pieces = self.cleaned_data.get("weekdays", [])
        if not pieces:
            raise forms.ValidationError("請至少設定一個執行星期。")
        return ",".join(sorted(set(pieces), key=int))

    def clean_drug_name(self):
        value = self.cleaned_data.get("drug_name", "").strip()
        if not value:
            raise forms.ValidationError("請輸入藥品名稱。")
        exact = Drug.objects.filter(
            Q(name_zh__iexact=value) | Q(generic_name__iexact=value) | Q(fda_product_ndc__iexact=value)
        ).first()
        if exact:
            self._selected_drug = exact
            return value
        self._selected_drug = Drug(name_zh=value, generic_name="")
        return value

    def clean(self):
        cleaned = super().clean()
        grace = cleaned.get("grace_minutes")
        missed = cleaned.get("missed_after_minutes")
        if grace and missed and missed <= grace:
            self.add_error("missed_after_minutes", "漏服判定分鐘必須大於感測器等待分鐘。")
        return cleaned

    def save(self, commit=True):
        schedule = super().save(commit=False)
        drug = getattr(self, "_selected_drug", None)
        if drug is not None:
            if not drug.pk:
                drug.save()
            schedule.drug = drug
        schedule.period = period_for_slot(schedule.slot)
        if commit:
            schedule.save()
            self.save_m2m()
        return schedule


class OpenFDASyncForm(forms.Form):
    query = forms.CharField(
        label="英文學名、品牌名或 Product NDC",
        max_length=120,
        widget=forms.TextInput(attrs={"class": INPUT, "placeholder": "例如 acetaminophen、metformin、50580-506"}),
    )
    limit = forms.IntegerField(
        label="每個 FDA 端點最多取回筆數",
        min_value=1,
        max_value=100,
        initial=10,
        widget=forms.NumberInput(attrs={"class": INPUT}),
    )


class KaggleImportForm(forms.Form):
    dataset_url = forms.CharField(
        label="資料集來源網址或名稱",
        required=False,
        help_text="可填推薦資料集網址、Kaggle 網址，或本機 CSV 來源名稱；空白時會用檔名保存來源。",
        widget=forms.TextInput(
            attrs={
                "class": INPUT,
                "placeholder": "例如 recommended: drugs-side-effects 或 https://www.kaggle.com/datasets/...",
            }
        ),
    )
    csv_file = forms.FileField(
        label="CSV 檔案",
        help_text="至少需包含藥名，以及副作用／交互作用／適應症／警告其中一欄。",
        widget=forms.ClearableFileInput(attrs={"class": INPUT, "accept": ".csv,text/csv"}),
    )

    def clean_dataset_url(self):
        return self.cleaned_data.get("dataset_url", "").strip()

    def clean_csv_file(self):
        uploaded = self.cleaned_data["csv_file"]
        if not uploaded.name.lower().endswith(".csv"):
            raise forms.ValidationError("只能匯入 CSV 檔案。")
        return uploaded


class QAForm(forms.Form):
    elder_name = forms.CharField(
        label="長輩姓名（選填）",
        required=False,
        max_length=50,
        widget=forms.TextInput(attrs={"class": INPUT}),
    )
    drug_name = forms.CharField(
        label="藥物名稱／英文學名／NDC",
        max_length=180,
        widget=forms.TextInput(attrs={"class": INPUT, "placeholder": "例如 acetaminophen"}),
    )
    question = forms.CharField(
        label="問題",
        widget=forms.Textarea(
            attrs={"class": INPUT, "rows": 4, "placeholder": "例如：為什麼要吃這顆藥？有什麼副作用？"}
        ),
    )
    language = forms.ChoiceField(
        label="回答語言",
        choices=[("zh-TW", "繁體中文（本機翻譯可用時）"), ("en", "FDA 英文原文")],
        initial="zh-TW",
        widget=forms.Select(attrs={"class": INPUT}),
    )
    auto_sync = forms.BooleanField(
        label="知識庫找不到時，自動查詢 openFDA 真實資料",
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": CHECKBOX}),
    )


class SensorDemoForm(forms.Form):
    device_id = forms.CharField(initial="pillbox-01", widget=forms.TextInput(attrs={"class": INPUT}))
    user_name = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": INPUT}))
    slot = forms.TypedChoiceField(label="藥盒時段", choices=SLOT_SELECT_CHOICES, coerce=int, initial=1, widget=forms.Select(attrs={"class": INPUT}))
