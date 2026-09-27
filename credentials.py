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
