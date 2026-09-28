"""A dedicated macOS Keychain entry; secret never appears in process arguments."""
import ctypes as C
import re

class Keychain:
    def __init__(self,service='com.osmanevski.fotografmasasi.openrouter'):
        self.service=service.encode();self.account=b'openrouter'
        self.sec=C.CDLL('/System/Library/Frameworks/Security.framework/Security')
        self.cf=C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self.cf.CFRelease.argtypes=[C.c_void_p]
        self.sec.SecKeychainFindGenericPassword.argtypes=[C.c_void_p,C.c_uint32,C.c_char_p,C.c_uint32,C.c_char_p,C.POINTER(C.c_uint32),C.POINTER(C.c_void_p),C.POINTER(C.c_void_p)]
        self.sec.SecKeychainAddGenericPassword.argtypes=[C.c_void_p,C.c_uint32,C.c_char_p,C.c_uint32,C.c_char_p,C.c_uint32,C.c_char_p,C.POINTER(C.c_void_p)]
        self.sec.SecKeychainItemModifyAttributesAndData.argtypes=[C.c_void_p,C.c_void_p,C.c_uint32,C.c_char_p]
        self.sec.SecKeychainItemFreeContent.argtypes=[C.c_void_p,C.c_void_p]
        self.sec.SecKeychainItemDelete.argtypes=[C.c_void_p]
    def find(self,read=False):
        length=C.c_uint32();data=C.c_void_p();item=C.c_void_p()
        status=self.sec.SecKeychainFindGenericPassword(None,len(self.service),self.service,len(self.account),self.account,C.byref(length) if read else None,C.byref(data) if read else None,C.byref(item))
        if status==-25300:return None,None
        if status:raise RuntimeError(f'Anahtar Zinciri açılamadı ({status}). macOS erişim iznini kontrol et.')
        value=None
        if read:
            try:value=C.string_at(data,length.value).decode()
            finally:self.sec.SecKeychainItemFreeContent(None,data)
        return item,value
    def get(self):
        item,value=self.find(True)
        if item:self.cf.CFRelease(item)
        if not value:raise ValueError('Önce OpenRouter API anahtarını kaydet.')
        return value
    def set(self,value):
        if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{20,512}',value):raise ValueError('Geçerli OpenRouter anahtarını gir; boşluk/satır sonu olmamalı.')
        raw=value.encode();item,_=self.find()
        try:
            status=self.sec.SecKeychainItemModifyAttributesAndData(item,None,len(raw),raw) if item else self.sec.SecKeychainAddGenericPassword(None,len(self.service),self.service,len(self.account),self.account,len(raw),raw,None)
            if status:raise RuntimeError(f'Anahtar Zinciri kaydı başarısız ({status}).')
        finally:
            if item:self.cf.CFRelease(item)
    def delete(self):
        item,_=self.find()
        if item:
            try:
                status=self.sec.SecKeychainItemDelete(item)
                if status:raise RuntimeError(f'Anahtar silinemedi ({status}).')
            finally:self.cf.CFRelease(item)

# Keep the legacy macOS service/account untouched for existing installations.
SERVICE = 'com.osmanevski.fotografmasasi.openrouter'
ACCOUNT = 'openrouter'


def validate_key(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{20,512}', value):
        raise ValueError('Geçerli OpenRouter anahtarını gir; boşluk/satır sonu olmamalı.')


class WindowsCredentials:
    """Native encrypted Windows Credential Manager, no third-party backend."""
    def __init__(self, service=SERVICE):
        from ctypes import wintypes as W
        class Credential(C.Structure):
            _fields_ = [('Flags', W.DWORD), ('Type', W.DWORD), ('TargetName', W.LPWSTR),
                        ('Comment', W.LPWSTR), ('LastWritten', W.FILETIME),
                        ('CredentialBlobSize', W.DWORD), ('CredentialBlob', C.POINTER(C.c_ubyte)),
                        ('Persist', W.DWORD), ('AttributeCount', W.DWORD), ('Attributes', C.c_void_p),
                        ('TargetAlias', W.LPWSTR), ('UserName', W.LPWSTR)]
        self.Credential = Credential
        self.service = service
        self.api = C.WinDLL('Advapi32.dll', use_last_error=True)
        self.api.CredReadW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.POINTER(C.POINTER(Credential))]
        self.api.CredReadW.restype = W.BOOL
        self.api.CredWriteW.argtypes = [C.POINTER(Credential), W.DWORD]
        self.api.CredWriteW.restype = W.BOOL
        self.api.CredDeleteW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD]
        self.api.CredDeleteW.restype = W.BOOL
        self.api.CredFree.argtypes = [C.c_void_p]
        self.api.CredFree.restype = None

    def get(self):
        pointer = C.POINTER(self.Credential)()
        if not self.api.CredReadW(self.service, 1, 0, C.byref(pointer)):
            code = C.get_last_error()
            if code == 1168:
                raise ValueError('Önce OpenRouter API anahtarını kaydet.')
            raise RuntimeError(f'Windows Credential Manager error ({code}).')
        try:
            return C.string_at(pointer.contents.CredentialBlob, pointer.contents.CredentialBlobSize).decode('utf-8')
        finally:
            self.api.CredFree(pointer)

    def set(self, value):
        validate_key(value)
        raw = value.encode('utf-8')
        blob = (C.c_ubyte * len(raw)).from_buffer_copy(raw)
        item = self.Credential(Type=1, TargetName=self.service, UserName=ACCOUNT,
                               CredentialBlobSize=len(raw), CredentialBlob=blob, Persist=2)
        if not self.api.CredWriteW(C.byref(item), 0):
            raise RuntimeError(f'Windows Credential Manager error ({C.get_last_error()}).')

    def delete(self):
        if not self.api.CredDeleteW(self.service, 1, 0):
            code = C.get_last_error()
            if code != 1168:
                raise RuntimeError(f'Windows Credential Manager error ({code}).')


class LinuxCredentials:
    """Secret Service via secret-tool. Secrets travel over stdin, never argv."""
    def __init__(self, service=SERVICE):
        self.service = service

    def _call(self, action, value=None):
        import shutil
        import subprocess
        tool = shutil.which('secret-tool')
        if not tool:
            raise RuntimeError('OpenRouter anahtarı için secret-tool ve açık bir Secret Service kasası gerekir. Yerel ve Codex modları kullanılabilir.')
        command = [tool, action]
        if action == 'store':
            command += ['--label=PhotoDesk OpenRouter']
        command += ['service', self.service, 'account', ACCOUNT]
        try:
            result = subprocess.run(command, input=value, capture_output=True, text=True,
                                    encoding='utf-8', timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError('Güvenli anahtar kasasına erişilemedi. Kasayı açıp yeniden dene.') from None
        if result.returncode:
            if action == 'lookup' and result.returncode == 1 and not result.stderr.strip():
                raise ValueError('Önce OpenRouter API anahtarını kaydet.')
            # Do not reflect provider stderr: it could contain a secret.
            raise RuntimeError('Güvenli anahtar kasasına erişilemedi. Kasayı açıp yeniden dene.')
        return result.stdout.rstrip('\r\n')

    def get(self):
        value = self._call('lookup')
        if not value:
            raise ValueError('Önce OpenRouter API anahtarını kaydet.')
        return value

    def set(self, value):
        validate_key(value)
        self._call('store', value)

    def delete(self):
        self._call('clear')


class Credentials:
    """No system libraries or credential store are touched during app startup."""
    def __init__(self):
        self.backend = None

    def _load(self):
        if self.backend is None:
            import sys
            self.backend = Keychain() if sys.platform == 'darwin' else WindowsCredentials() if sys.platform == 'win32' else LinuxCredentials()
        return self.backend

    def get(self):
        return self._load().get()

    def set(self, value):
        validate_key(value)
        self._load().set(value)

    def delete(self):
        self._load().delete()
