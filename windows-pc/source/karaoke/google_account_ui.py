"""Separate, visible Google account home for the Windows X-Stage player.

Only refresh credentials are persisted, using the existing per-user DPAPI file.
The profile photo is downloaded to memory, never written to Data or sent to the web.
This module contains no OAuth-JSON file picker: the existing approved Desktop
Client is discovered automatically from the installed app's Data directory.
"""
from __future__ import annotations

import io
import json
import logging
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

MIDNIGHT = '#081426'
CARD = '#12243c'
LIGHT = '#eaf7ff'
AQUA = '#69e8dd'
SILVER = '#a5bdd1'


class _NoImageRedirect(HTTPRedirectHandler):
    """Do not follow a Google-image redirect to another network host."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def safe_profile_picture(url: str, *, opener=None) -> bytes | None:
    """Download a small image only from Google's image-service HTTPS hosts."""
    if not isinstance(url, str) or len(url) > 1024:
        return None
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme != 'https' or not (host == 'googleusercontent.com' or host.endswith('.googleusercontent.com')):
        return None
    try:
        request = Request(url, headers={'User-Agent': 'X-Stage-Karaoke/0.9', 'Accept': 'image/*'})
        download = opener if opener is not None else build_opener(_NoImageRedirect()).open
        with download(request, timeout=7) as response:
            final_host = (urlparse(response.geturl()).hostname or '').lower()
            if final_host != host:
                return None
            media = response.headers.get('Content-Type', '').lower()
            if not media.startswith('image/'):
                return None
            data = response.read(256 * 1024 + 1)
            return data if 0 < len(data) <= 256 * 1024 else None
    except (OSError, ValueError):
        logging.info('Google profile photo unavailable; showing initials instead')
        return None


def fetch_google_profile(token: str, *, request=None) -> dict:
    """Fetch verified account presentation data. No refresh token is passed."""
    if request is None:
        from .google_drive_sync import _request as request
    try:
        _, _, content = request('https://openidconnect.googleapis.com/v1/userinfo', token, timeout=12)
        data = json.loads(content)
        if data.get('email_verified') is not True or not data.get('email'):
            return {}
        return {
            'email': str(data['email']),
            'name': str(data.get('name') or data.get('given_name') or '').strip()[:110],
            'picture': str(data.get('picture') or '')[:1024],
        }
    except (OSError, ValueError, KeyError, RuntimeError, TimeoutError):
        logging.info('Google display profile unavailable; email identity remains available')
        return {}


def display_identity(profile: dict | None, email: str) -> str:
    """Never replace the verified email with an identity from another account."""
    verified = (profile or {}).get('email', '')
    if verified and verified.casefold() == str(email).casefold():
        return (profile or {}).get('name') or email
    return email


class GoogleAccountUI:
    def __init__(self, app, *, online_only=False):
        self.app = app
        self.online_only = bool(online_only)
        self.credentials = None
        self.profile = {}
        self.auth_busy = False
        self._messages = queue.SimpleQueue()
        self._generation = 0
        self._photo = None
        self._closed = False
        self._timers = set()
        app.bind('<Destroy>', self._on_destroy, add='+')
        self._create_ui()
        if self.online_only:
            # The playback screen stays clean. Google controls are exposed only
            # through the X-Stage Online wizard opened from the context menu.
            self.bar.place_forget()
        self._set_identity(None)
        self._schedule(100, self._poll)
        self._schedule(250, self._startup)

    def _schedule(self, delay_ms, callback):
        if self._closed:
            return
        holder = [None]
        def invoke():
            self._timers.discard(holder[0])
            if not self._closed and self.app.winfo_exists():
                callback()
        holder[0] = self.app.after(delay_ms, invoke)
        self._timers.add(holder[0])

    def _on_destroy(self, event):
        if event.widget is self.app:
            self.close()

    def _create_ui(self):
        app = self.app
        host = getattr(app, 'surface', app)
        self.bar = tk.Frame(host, bg='#06192e', highlightbackground='#246077', highlightthickness=1)
        self.bar.place(x=0, y=0, relwidth=1, height=62)
        tk.Label(self.bar, text='X-STAGE', fg=AQUA, bg='#06192e',
                 font=('Segoe UI', 17, 'bold')).pack(side='left', padx=(18, 5))
        tk.Label(self.bar, text='KARAOKE', fg=LIGHT, bg='#06192e',
                 font=('Segoe UI', 12, 'bold')).pack(side='left')
        tk.Button(self.bar, text='หน้าแรก / Google', command=self.show_home, fg=LIGHT, bg='#213954',
                  relief='flat', padx=13, pady=5).pack(side='right', padx=(0, 13))
        self.profile_button = tk.Button(self.bar, text='●  ยังไม่เข้าสู่ระบบ', command=self.show_home,
                  fg=LIGHT, bg='#14394d', relief='flat', padx=12, pady=5)
        self.profile_button.pack(side='right', padx=7)
        self.photo_label = tk.Label(self.bar, text='G', fg='#06213b', bg=AQUA,
                                    font=('Segoe UI', 12, 'bold'), width=3, height=2)
        self.photo_label.pack(side='right', padx=(0, 4))
        self.home = tk.Frame(host, bg=MIDNIGHT)
        self.card = tk.Frame(self.home, bg=CARD, highlightthickness=1,
                             highlightbackground='#2e8090', padx=34, pady=26)
        self.card.place(relx=.5, rely=.5, anchor='center')
        tk.Label(self.card, text='X-STAGE KARAOKE', fg=AQUA, bg=CARD,
                 font=('Segoe UI', 29, 'bold')).pack(anchor='w')
        tk.Label(self.card, text='WELCOME  •  GOOGLE DRIVE', fg=SILVER, bg=CARD,
                 font=('Segoe UI', 11, 'bold')).pack(anchor='w', pady=(0, 20))
        self.home_status = tk.StringVar(value='เชื่อมต่อ Google เพื่อซิงค์เพลงออนไลน์')
        tk.Label(self.card, textvariable=self.home_status, fg=LIGHT, bg=CARD,
                 wraplength=490, justify='left', font=('Leelawadee UI', 12)).pack(anchor='w', pady=(0, 18))
        self.login_button = tk.Button(self.card, text='G   เข้าสู่ระบบ Google Drive',
                                      command=self.login, fg='#041a26', bg=AQUA,
                                      font=('Leelawadee UI', 12, 'bold'), padx=20, pady=12,
                                      relief='flat', cursor='hand2')
        self.login_button.pack(fill='x', pady=(0, 9))
        self.continue_button = tk.Button(self.card, text='เข้าสู่เวที / ใช้งานแบบออฟไลน์',
                                      command=self.hide_home, fg=LIGHT, bg='#24405b',
                                      font=('Leelawadee UI', 11), padx=16, pady=10, relief='flat')
        self.continue_button.pack(fill='x')
        self.logout_button = tk.Button(self.card, text='ออกจากระบบและยกเลิกการจดจำบัญชี',
                                      command=self.logout, fg='#f2bac6', bg=CARD,
                                      font=('Leelawadee UI', 10), bd=0, relief='flat')
        self.logout_button.pack(anchor='center', pady=(20, 0))
        tk.Label(self.card,
                 text='ไฟล์ OAuth Desktop JSON เดิมจะถูกตรวจหาใน Data อัตโนมัติ\n'
                      'หากยังไม่มีไฟล์ ให้ติดตั้ง google-oauth-client.json ใน Data\n'
                      'ข้อมูลเพลงยังอยู่ในเครื่องและ Google Drive ส่วนตัว',
                 fg=SILVER, bg=CARD, justify='center', font=('Leelawadee UI', 9)).pack(pady=(12, 0))
        self.home.bind('<Configure>', lambda _e:self._resize_card(), add='+')

    def _resize_card(self):
        if not self._closed:
            width = max(300, min(600, self.home.winfo_width() - 30))
            self.card.configure(width=width)

    def show_home(self):
        if self._closed:
            return
        self.home.place(x=0, y=0, relwidth=1, relheight=1)
        self.home.lift()
        self.bar.lift()
        if self.credentials:
            self.home_status.set('เชื่อมต่อบัญชี Google แล้ว: ' + self.credentials[1] + '\nพร้อมซิงค์ออนไลน์จากเมนู X-Stage')
        elif not self.auth_busy:
            self.home_status.set('เข้าสู่ระบบเพื่อเชื่อมคลัง Google Drive หรือใช้เวทีแบบออฟไลน์')

    def hide_home(self):
        self.home.place_forget()
        self.bar.lift()
        try:
            self.app.focus_song_input()
        except (AttributeError, tk.TclError):
            pass

    def _set_identity(self, email: str | None):
        if email:
            label = display_identity(self.profile, email)
            shown_name = label[:30] + ('…' if len(label) > 30 else '')
            self.profile_button.configure(text=shown_name if label == email else shown_name + '\n' + email[:36])
            self.login_button.configure(text='G   สลับบัญชี Google')
            self.logout_button.pack(anchor='center', pady=(18, 0))
        else:
            self.profile_button.configure(text='●  ยังไม่เข้าสู่ระบบ')
            self.login_button.configure(text='G   เข้าสู่ระบบ Google Drive')
            self.logout_button.pack_forget()
            self.photo_label.configure(text='G', image='', fg='#06213b', bg=AQUA, width=3, height=2)
            self._photo = None

    def _startup(self):
        if self._closed:
            return
        from .google_session import has_saved_session
        if not self.online_only:
            self.show_home()
            if has_saved_session(self.app.data_dir):
                self._begin('restore')

    def ensure_online_session(self):
        """Restore the saved Google account only when Online menu is opened."""
        from .google_session import has_saved_session
        if not self._closed and not self.auth_busy and not self.credentials and \
                has_saved_session(self.app.data_dir):
            self._begin('restore')

    def login(self):
        active = getattr(self.app, '_online_sync_thread', None)
        if active is not None and active.is_alive():
            self.home_status.set('กำลังซิงค์เพลงอยู่ • กรุณารอให้เสร็จก่อนเปลี่ยนบัญชี Google')
            return
        self._begin('login')

    def _begin(self, mode):
        if self._closed or self.auth_busy:
            return
        from .google_drive_sync import load_client
        try:
            load_client(self.app.home, self.app.data_dir)
        except (ValueError, OSError) as exc:
            self.home_status.set('Google Login ยังไม่พร้อม: '+str(exc))
            if not self.online_only:
                self.show_home()
            return
        self.auth_busy = True
        self._generation += 1
        serial = self._generation
        self.login_button.configure(state='disabled')
        self.home_status.set('กำลังเชื่อมต่อบัญชีที่จดจำ…' if mode == 'restore' else 'กำลังเปิด Google ในเบราว์เซอร์…')
        threading.Thread(target=self._worker, args=(mode,serial), name='xstage-google-account', daemon=True).start()

    def _worker(self, mode, serial):
        try:
            from .google_drive_sync import load_client, sign_in
            from .google_session import restore_session, save_session
            client_id, client_secret = load_client(self.app.home, self.app.data_dir)
            if mode == 'restore':
                credentials = restore_session(self.app.home, self.app.data_dir)
                if credentials is None:
                    raise RuntimeError('ไม่มีบัญชี Google ที่เคยจดจำ')
            else:
                credentials = sign_in(client_id, client_secret)
                if self._generation == serial:
                    from .google_session import has_saved_session, load_session, forget_session
                    if credentials[2]:
                        save_session(self.app.data_dir, client_id, credentials[1], credentials[2])
                    elif has_saved_session(self.app.data_dir):
                        # Do not silently restore a different account on next boot.
                        remembered = load_session(self.app.data_dir)
                        if remembered['client_id'] != client_id or remembered['email'].casefold() != credentials[1].casefold():
                            forget_session(self.app.data_dir)
            # Give control back immediately; profile/picture are optional extras.
            self._messages.put((serial, 'ready', (credentials, {}, None)))
            try:
                profile = fetch_google_profile(credentials[0])
                if profile.get('email') and profile['email'].casefold() != credentials[1].casefold():
                    profile = {}
                picture = safe_profile_picture(profile.get('picture', ''))
                self._messages.put((serial, 'profile', (profile, picture)))
            except Exception:
                # An optional avatar must never erase a successfully connected account.
                logging.exception('Optional Google profile/avatar load failed')
        except Exception as exc:
            self._messages.put((serial, 'error', str(exc)))

    def _set_photo(self, image_data):
        self._photo = None
        if not image_data:
            self.photo_label.configure(text='G', image='', bg=AQUA, width=3, height=2)
            return
        try:
            from PIL import Image, ImageTk, ImageDraw
            with Image.open(io.BytesIO(image_data)) as source:
                if source.width * source.height > 6_000_000:
                    raise ValueError('Google profile picture is too large')
                image = source.convert('RGBA')
            image.thumbnail((35, 35), Image.Resampling.LANCZOS)
            square = Image.new('RGBA', (36, 36), (0, 0, 0, 0))
            square.alpha_composite(image, ((36-image.width)//2, (36-image.height)//2))
            mask = Image.new('L', (36, 36))
            ImageDraw.Draw(mask).ellipse((0, 0, 35, 35), fill=255)
            square.putalpha(mask)
            self._photo = ImageTk.PhotoImage(square, master=self.app)
            self.photo_label.configure(image=self._photo, text='', width=36, height=36)
        except (OSError, ValueError, ImportError):
            self.photo_label.configure(text='G', image='', bg=AQUA, width=3, height=2)

    def _poll(self):
        if self._closed or not self.app.winfo_exists():
            return
        try:
            while True:
                serial, kind, payload = self._messages.get_nowait()
                if serial != self._generation:
                    continue
                self.auth_busy = False
                self.login_button.configure(state='normal')
                if kind == 'ready':
                    self.credentials, self.profile, picture = payload
                    self._set_identity(self.credentials[1])
                    self._set_photo(picture)
                    self.home_status.set('✓ เชื่อมต่อ Google Drive แล้ว: '+self.credentials[1])
                    if not self.online_only:
                        self._schedule(450, self.hide_home)
                elif kind == 'profile':
                    if self.credentials:
                        self.profile, picture = payload
                        self._set_identity(self.credentials[1])
                        self._set_photo(picture)
                else:
                    self.credentials = None
                    self.profile = {}
                    self._set_identity(None)
                    self.home_status.set('เชื่อมต่อไม่ได้: ' + str(payload))
                    if not self.online_only:
                        self.show_home()
        except queue.Empty:
            pass
        self._schedule(120, self._poll)

    def logout(self):
        active = getattr(self.app, '_online_sync_thread', None)
        if self.auth_busy or (active is not None and active.is_alive()):
            messagebox.showinfo('Google Drive', 'กรุณารอให้การเชื่อมต่อหรือซิงค์จบก่อนออกจากระบบ', parent=self.app)
            return
        from .google_session import forget_session
        forget_session(self.app.data_dir)
        self._generation += 1
        self.credentials = None
        self.profile = {}
        self._set_identity(None)
        self.home_status.set('ออกจากระบบและยกเลิกการจดจำบัญชีนี้แล้ว')
        if not self.online_only:
            self.show_home()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._generation += 1
        for timer in tuple(self._timers):
            try:
                self.app.after_cancel(timer)
            except tk.TclError:
                pass
        self._timers.clear()
        self.credentials = None
        self._photo = None
