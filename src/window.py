# window.py
#
# Copyright 2024 Jeffser
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Handles the main window
"""
import json, threading, os, re, base64, gettext, uuid, shutil, logging, time, requests, sqlite3
import odf.opendocument as odfopen
import odf.table as odftable
from io import BytesIO
from PIL import Image
from pypdf import PdfReader
from datetime import datetime
from pydbus import SessionBus, Variant

import gi
gi.require_version('GtkSource', '5')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('Spelling', '1')
from gi.repository import Adw, Gtk, Gdk, GLib, GtkSource, Gio, GdkPixbuf, Spelling

from . import connection_handler, generic_actions
from .custom_widgets import message_widget, chat_widget, model_widget, terminal_widget, dialog_widget
from .internal import config_dir, data_dir, cache_dir, source_dir

logger = logging.getLogger(__name__)

@Gtk.Template(resource_path='/com/jeffser/Alpaca/window.ui')
class AlpacaWindow(Adw.ApplicationWindow):

    __gtype_name__ = 'AlpacaWindow'

    localedir = os.path.join(source_dir, 'locale')

    gettext.bindtextdomain('com.jeffser.Alpaca', localedir)
    gettext.textdomain('com.jeffser.Alpaca')
    _ = gettext.gettext

    #Variables
    attachments = {}

    #Override elements
    overrides_group = Gtk.Template.Child()
    instance_page = Gtk.Template.Child()

    #Elements
    split_view_overlay = Gtk.Template.Child()
    regenerate_button : Gtk.Button = None
    selected_chat_row : Gtk.ListBoxRow = None
    create_model_base = Gtk.Template.Child()
    create_model_name = Gtk.Template.Child()
    create_model_system = Gtk.Template.Child()
    create_model_modelfile = Gtk.Template.Child()
    create_model_modelfile_section = Gtk.Template.Child()
    tweaks_group = Gtk.Template.Child()
    preferences_dialog = Gtk.Template.Child()
    shortcut_window : Gtk.ShortcutsWindow  = Gtk.Template.Child()
    file_preview_dialog = Gtk.Template.Child()
    file_preview_text_label = Gtk.Template.Child()
    file_preview_image = Gtk.Template.Child()
    welcome_dialog = Gtk.Template.Child()
    welcome_carousel = Gtk.Template.Child()
    welcome_previous_button = Gtk.Template.Child()
    welcome_next_button = Gtk.Template.Child()
    main_overlay = Gtk.Template.Child()
    manage_models_overlay = Gtk.Template.Child()
    chat_stack = Gtk.Template.Child()
    message_text_view = None
    message_text_view_scrolled_window = Gtk.Template.Child()
    send_button = Gtk.Template.Child()
    stop_button = Gtk.Template.Child()
    attachment_container = Gtk.Template.Child()
    attachment_box = Gtk.Template.Child()
    file_filter_db = Gtk.Template.Child()
    file_filter_gguf = Gtk.Template.Child()
    file_filter_attachments = Gtk.Template.Child()
    attachment_button = Gtk.Template.Child()
    chat_right_click_menu = Gtk.Template.Child()
    send_message_menu = Gtk.Template.Child()
    attachment_menu = Gtk.Template.Child()
    model_tag_list_box = Gtk.Template.Child()
    navigation_view_manage_models = Gtk.Template.Child()
    file_preview_open_button = Gtk.Template.Child()
    file_preview_remove_button = Gtk.Template.Child()
    model_searchbar = Gtk.Template.Child()
    message_searchbar = Gtk.Template.Child()
    message_search_button = Gtk.Template.Child()
    searchentry_messages = Gtk.Template.Child()
    no_results_page = Gtk.Template.Child()
    model_link_button = Gtk.Template.Child()
    title_stack = Gtk.Template.Child()
    manage_models_dialog = Gtk.Template.Child()
    model_scroller = Gtk.Template.Child()
    model_detail_header = Gtk.Template.Child()
    model_detail_information = Gtk.Template.Child()
    model_detail_categories = Gtk.Template.Child()
    model_detail_system = Gtk.Template.Child()
    model_detail_create_button = Gtk.Template.Child()
    ollama_information_label = Gtk.Template.Child()
    default_model_combo = Gtk.Template.Child()
    default_model_list = Gtk.Template.Child()
    model_directory_selector = Gtk.Template.Child()
    remote_connection_selector = Gtk.Template.Child()
    model_tag_flow_box = Gtk.Template.Child()

    chat_list_container = Gtk.Template.Child()
    chat_list_box = None
    ollama_instance = None
    model_manager = None
    instance_idle_timer = Gtk.Template.Child()

    background_switch = Gtk.Template.Child()
    powersaver_warning_switch = Gtk.Template.Child()
    remote_connection_switch = Gtk.Template.Child()

    banner = Gtk.Template.Child()

    terminal_scroller = Gtk.Template.Child()
    terminal_dialog = Gtk.Template.Child()

    quick_ask = Gtk.Template.Child()
    quick_ask_overlay = Gtk.Template.Child()
    quick_ask_save_button = Gtk.Template.Child()

    sqlite_path = os.path.join(data_dir, "alpaca.db")

    @Gtk.Template.Callback()
    def remote_connection_selector_clicked(self, button):
        options = {
            _("Cancel"): {"callback": lambda *_: None},
            _("Connect"): {"callback": lambda url, bearer: generic_actions.connect_remote(url, bearer), "appearance": "suggested"}
        }
        entries = [
            {"text": self.ollama_instance.remote_url, "placeholder": _('Server URL')},
            {"text": self.ollama_instance.bearer_token, "placeholder": _('Bearer Token (Optional)')}
        ]
        dialog_widget.Entry(
            _('Connect Remote Instance'),
            _('Enter instance information to continue'),
            list(options)[0],
            options,
            entries
        )

    @Gtk.Template.Callback()
    def model_directory_selector_clicked(self, button):
        def directory_selected(result):
            button.set_sensitive(False)
            selected_directory = result.get_path()
            self.ollama_instance.model_directory = selected_directory
            self.model_directory_selector.set_subtitle(selected_directory)
            if not self.ollama_instance.remote:
                self.ollama_instance.reset()
            sqlite_con = sqlite3.connect(self.sqlite_path)
            cursor = sqlite_con.cursor()
            cursor.execute("UPDATE preferences SET value=?, type=? WHERE id=?", (self.ollama_instance.model_directory, str(type(self.ollama_instance.model_directory)), "model_directory"))
            sqlite_con.commit()
            sqlite_con.close()
            self.refresh_local_models()
            button.set_sensitive(True)
        dialog_widget.simple_directory(directory_selected)

    @Gtk.Template.Callback()
    def refresh_local_models(self, button=None):
        logger.info("Refreshing local model list")
        self.model_manager.update_local_list()

    @Gtk.Template.Callback()
    def stop_message(self, button=None):
        self.chat_list_box.get_current_chat().stop_message()

    @Gtk.Template.Callback()
    def send_message(self, button=None, system:bool=False):
        if button and not button.get_visible():
            return
        if not self.message_text_view.get_buffer().get_text(self.message_text_view.get_buffer().get_start_iter(), self.message_text_view.get_buffer().get_end_iter(), False):
            return
        current_chat = self.chat_list_box.get_current_chat()
        if current_chat.busy == True:
            return

        self.chat_list_box.send_tab_to_top(self.chat_list_box.get_selected_row())

        current_model = self.model_manager.get_selected_model()
        if current_model is None:
            self.show_toast(_("Please select a model before chatting"), self.main_overlay)
            return

        sqlite_con = sqlite3.connect(self.sqlite_path)
        cursor = sqlite_con.cursor()

        message_id = self.generate_uuid()

        raw_message = self.message_text_view.get_buffer().get_text(self.message_text_view.get_buffer().get_start_iter(), self.message_text_view.get_buffer().get_end_iter(), False)
        current_chat.add_message(message_id, None, system)
        m_element = current_chat.messages[message_id]

        for name, content in self.attachments.items():
            cursor.execute("INSERT INTO attachment (id, message_id, type, name, content) VALUES (?, ?, ?, ?, ?)",(
                self.generate_uuid(), message_id, content['type'], name, content['content']))
            m_element.add_attachment(name, content['type'], content['content'])
            content["button"].get_parent().remove(content["button"])
        self.attachments = {}
        self.attachment_box.set_visible(False)

        m_element.set_text(raw_message)
        m_element.add_footer(datetime.now())

        cursor.execute("INSERT INTO message (id, chat_id, role, model, date_time, content) VALUES (?, ?, ?, ?, ?, ?)",
                (m_element.message_id, current_chat.chat_id, 'system' if system else 'user', None, m_element.dt.strftime("%Y/%m/%d %H:%M:%S"), m_element.text))

        self.message_text_view.get_buffer().set_text("", 0)

        if system:
            if current_chat.welcome_screen:
                current_chat.welcome_screen.set_visible(False)
        else:
            data = {
                "model": current_model,
                "messages": current_chat.convert_to_ollama(),
                "options": {"temperature": self.ollama_instance.tweaks["temperature"]},
                "keep_alive": f"{self.ollama_instance.tweaks['keep_alive']}m",
                "stream": True
            }
            if self.ollama_instance.tweaks["seed"] != 0:
                data['options']['seed'] = self.ollama_instance.tweaks["seed"]

            bot_id=self.generate_uuid()
            current_chat.add_message(bot_id, current_model, False)
            m_element_bot = current_chat.messages[bot_id]
            m_element_bot.set_text()
            cursor.execute("INSERT INTO message (id, chat_id, role, model, date_time, content) VALUES (?, ?, ?, ?, ?, ?)",
                (m_element_bot.message_id, current_chat.chat_id, 'assistant', current_model, m_element.dt.strftime("%Y/%m/%d %H:%M:%S"), '(No Text)'))
            threading.Thread(target=self.run_message, args=(data, m_element_bot, current_chat)).start()

        sqlite_con.commit()
        sqlite_con.close()

    @Gtk.Template.Callback()
    def welcome_carousel_page_changed(self, carousel, index):
        logger.debug("Showing welcome carousel")
        if index == 0:
            self.welcome_previous_button.set_sensitive(False)
        else:
            self.welcome_previous_button.set_sensitive(True)
        if index == carousel.get_n_pages()-1:
            self.welcome_next_button.set_label(_("Close"))
            self.welcome_next_button.set_tooltip_text(_("Close"))
        else:
            self.welcome_next_button.set_label(_("Next"))
            self.welcome_next_button.set_tooltip_text(_("Next"))

    @Gtk.Template.Callback()
    def welcome_previous_button_activate(self, button):
        self.welcome_carousel.scroll_to(self.welcome_carousel.get_nth_page(self.welcome_carousel.get_position()-1), True)

    @Gtk.Template.Callback()
    def welcome_next_button_activate(self, button):
        if button.get_label() == "Next":
            self.welcome_carousel.scroll_to(self.welcome_carousel.get_nth_page(self.welcome_carousel.get_position()+1), True)
        else:
            self.welcome_dialog.force_close()
            self.powersaver_warning_switch.set_active(True)
            sqlite_con = sqlite3.connect(self.sqlite_path)
            cursor = sqlite_con.cursor()
            cursor.execute("UPDATE preferences SET value=?, type=? WHERE id=?", (not shutil.which('ollama'), str(type(not shutil.which('ollama'))), "run_remote"))
            cursor.execute("UPDATE preferences SET value=?, type=? WHERE id=?", (False, str(type(False)), "show_welcome_dialog"))
            sqlite_con.commit()
            sqlite_con.close()
            threading.Thread(target=self.prepare_alpaca).start()

    @Gtk.Template.Callback()
    def switch_run_on_background(self, switch, user_data):
        logger.debug("Switching run on background")
        self.set_hide_on_close(switch.get_active())
        sqlite_con = sqlite3.connect(self.sqlite_path)
        cursor = sqlite_con.cursor()
        cursor.execute("UPDATE preferences SET value=?, type=? WHERE id=?", (switch.get_active(), str(type(switch.get_active())), "run_on_background"))
        sqlite_con.commit()
        sqlite_con.close()
    
    @Gtk.Template.Callback()
    def switch_powersaver_warning(self, switch, user_data):
        logger.debug("Switching powersaver warning banner")
        if switch.get_active():
            self.banner.set_revealed(Gio.PowerProfileMonitor.dup_default().get_power_saver_enabled())
        else:
            self.banner.set_revealed(False)
        sqlite_con = sqlite3.connect(self.sqlite_path)
        cursor = sqlite_con.cursor()
        cursor.execute("UPDATE preferences SET value=?, type=? WHERE id=?", (switch.get_active(), str(type(switch.get_active())), "powersaver_warning"))
        sqlite_con.commit()
        sqlite_con.close()

    @Gtk.Template.Callback()
    def changed_default_model(self, comborow, user_data):
        logger.debug("Changed default model")
        default_model = self.convert_model_name(self.default_model_list.get_string(self.default_model_combo.get_selected()), 1)
        sqlite_con = sqlite3.connect(self.sqlite_path)
        cursor = sqlite_con.cursor()
        cursor.execute("UPDATE preferences SET value=?, type=? WHERE id=?", (default_model, str(type(default_model)), "default_model"))
        sqlite_con.commit()
        sqlite_con.close()

    @Gtk.Template.Callback()
    def closing_app(self, user_data):
        selected_chat = self.chat_list_box.get_selected_row().chat_window.get_name()
        sqlite_con = sqlite3.connect(self.sqlite_path)
        cursor = sqlite_con.cursor()
        cursor.execute("UPDATE preferences SET value=?, type=? WHERE id=?", (selected_chat, str(type(selected_chat)), 'selected_chat'))
        sqlite_con.commit()
        sqlite_con.close()
        if self.get_hide_on_close():
            logger.info("Hiding app...")
        else:
            logger.info("Closing app...")
            self.ollama_instance.stop()
            self.get_application().quit()

    @Gtk.Template.Callback()
    def model_spin_changed(self, spin):
        value = spin.get_value()
        if spin.get_name() != "temperature":
            value = round(value)
        else:
            value = round(value, 1)
        if self.ollama_instance.tweaks[spin.get_name()] != value:
            self.ollama_instance.tweaks[spin.get_name()] = value
            sqlite_con = sqlite3.connect(self.sqlite_path)
            cursor = sqlite_con.cursor()
            cursor.execute("UPDATE preferences SET value=?, type=? WHERE id=?", (value, str(type(value)), spin.get_name()))
            sqlite_con.commit()
            sqlite_con.close()

    @Gtk.Template.Callback()
    def instance_idle_timer_changed(self, spin):
        self.ollama_instance.idle_timer_delay = round(spin.get_value())
        sqlite_con = sqlite3.connect(self.sqlite_path)
        cursor = sqlite_con.cursor()
        cursor.execute("UPDATE preferences SET value=?, type=? WHERE id=?", (self.ollama_instance.idle_timer_delay, str(type(self.ollama_instance.idle_timer_delay)), "idle_timer"))
        sqlite_con.commit()
        sqlite_con.close()

    @Gtk.Template.Callback()
    def create_model_start(self, button):
        name = self.create_model_name.get_text().lower().replace(":", "").replace(" ", "-")
        modelfile_buffer = self.create_model_modelfile.get_buffer()
        modelfile_raw = modelfile_buffer.get_text(modelfile_buffer.get_start_iter(), modelfile_buffer.get_end_iter(), False)
        modelfile = ["FROM {}".format(self.create_model_base.get_subtitle()), "SYSTEM {}".format(self.create_model_system.get_text())]
        for line in modelfile_raw.split('\n'):
            if not line.startswith('SYSTEM') and not line.startswith('FROM'):
                modelfile.append(line)
        threading.Thread(target=self.model_manager.pull_model, kwargs={"model_name": name, "modelfile": '\n'.join(modelfile)}).start()
        self.navigation_view_manage_models.pop()

    @Gtk.Template.Callback()
    def override_changed(self, entry):
        name = entry.get_name()
        value = entry.get_text()
        if self.ollama_instance:
            if value:
                self.ollama_instance.overrides[name] = value
            elif name in self.ollama_instance.overrides:
                del self.ollama_instance.overrides[name]
            if not self.ollama_instance.remote:
                self.ollama_instance.reset()
            sqlite_con = sqlite3.connect(self.sqlite_path)
            cursor = sqlite_con.cursor()
            cursor.execute("UPDATE overrides SET value=? WHERE id=?", (value, name))
            sqlite_con.commit()
            sqlite_con.close()

    @Gtk.Template.Callback()
    def link_button_handler(self, button):
        try:
            Gio.AppInfo.launch_default_for_uri(button.get_name())
        except Exception as e:
            logger.error(e)

    @Gtk.Template.Callback()
    def model_search_toggle(self, button):
        self.model_searchbar.set_search_mode(button.get_active())
        self.model_manager.pulling_list.set_visible(not button.get_active() and len(list(self.model_manager.pulling_list)) > 0)
        self.model_manager.local_list.set_visible(not button.get_active() and len(list(self.model_manager.local_list)) > 0)

    @Gtk.Template.Callback()
    def message_search_toggle(self, button):
        self.message_searchbar.set_search_mode(button.get_active())

    @Gtk.Template.Callback()
    def model_search_changed(self, entry):
        results = 0
        if self.model_manager:
            for model in list(self.model_manager.available_list):
                model.set_visible(re.search(entry.get_text(), '{} {} {} {} {}'.format(model.get_name(), model.model_title, model.model_author, model.model_description, (_('image') if model.image_recognition else '')), re.IGNORECASE))
                if model.get_visible():
                    results += 1
            if entry.get_text() and results == 0:
                self.no_results_page.set_visible(True)
                self.model_scroller.set_visible(False)
            else:
                self.model_scroller.set_visible(True)
                self.no_results_page.set_visible(False)

    @Gtk.Template.Callback()
    def message_search_changed(self, entry, current_chat=None):
        search_term=entry.get_text()
        results = 0
        if not current_chat:
            current_chat = self.chat_list_box.get_current_chat()
        if current_chat:
            try:
                for key, message in current_chat.messages.items():
                    if message and message.text:
                        message.set_visible(re.search(search_term, message.text, re.IGNORECASE))
                        for block in message.content_children:
                            if isinstance(block, message_widget.text_block):
                                if search_term:
                                    highlighted_text = re.sub(f"({re.escape(search_term)})", r"<span background='yellow' bgalpha='30%'>\1</span>", block.get_text(),flags=re.IGNORECASE)
                                    block.set_markup(highlighted_text)
                                else:
                                    block.set_markup(block.get_text())
            except Exception as e:
                pass

    @Gtk.Template.Callback()
    def model_detail_create_button_clicked(self, button):
        self.create_model(button.get_name(), False)

    def convert_model_name(self, name:str, mode:int) -> str: # mode=0 name:tag -> Name (tag)   |   mode=1 Name (tag) -> name:tag
        try:
            if mode == 0:
                return "{} ({})".format(name.split(":")[0].replace("-", " ").title(), name.split(":")[1])
            if mode == 1:
                return "{}:{}".format(name.split(" (")[0].replace(" ", "-").lower(), name.split(" (")[1][:-1])
        except Exception as e:
            pass

    @Gtk.Template.Callback()
    def quick_ask_save(self, button):
        self.quick_ask.close()
        chat = self.quick_ask_overlay.get_child()
        chat_name = self.generate_numbered_name(chat.get_name(), [tab.chat_window.get_name() for tab in self.chat_list_box.tab_list])
        new_chat = self.chat_list_box.new_chat(chat_name)
        sqlite_con = sqlite3.connect(self.sqlite_path)
        cursor = sqlite_con.cursor()
        for message in chat.messages.values():
            message_author = 'user'
            if message.bot:
                message_author = 'assistant'
            if message.system:
                message_author = 'system'
            cursor.execute("INSERT INTO message (id, chat_id, role, model, date_time, content) VALUES (?, ?, ?, ?, ?, ?)",
                (message.message_id, new_chat.chat_id, message_author, message.model, message.dt.strftime("%Y/%m/%d %H:%M:%S"), message.text))
        sqlite_con.commit()
        sqlite_con.close()
        threading.Thread(target=new_chat.load_chat_messages).start()
        self.present()

    @Gtk.Template.Callback()
    def closing_quick_ask(self, user_data):
        if not self.get_visible():
            self.close()

    def on_clipboard_paste(self, textview):
        logger.debug("Pasting from clipboard")
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.read_text_async(None, lambda clipboard, result: self.cb_text_received(clipboard.read_text_finish(result)))
        clipboard.read_texture_async(None, self.cb_image_received)

    def check_alphanumeric(self, editable, text, length, position, allowed_chars):
        new_text = ''.join([char for char in text if char.isalnum() or char in allowed_chars])
        if new_text != text:
            editable.stop_emission_by_name("insert-text")

    def create_model(self, model:str, file:bool):
        modelfile_buffer = self.create_model_modelfile.get_buffer()
        modelfile_buffer.delete(modelfile_buffer.get_start_iter(), modelfile_buffer.get_end_iter())
        self.create_model_system.set_text('')
        if not file:
            data = self.model_manager.model_selector.get_model_by_name(self.convert_model_name(model, 1)).data
            modelfile = []
            if 'system' in data and data['system']:
                self.create_model_system.set_text(data['system'])
            for line in data['modelfile'].split('\n'):
                if not line.startswith('SYSTEM') and not line.startswith('FROM') and not line.startswith('#'):
                    modelfile.append(line)
            self.create_model_name.set_text(self.convert_model_name(model, 1).split(':')[0] + "-custom")
            modelfile_buffer.insert(modelfile_buffer.get_start_iter(), '\n'.join(modelfile), len('\n'.join(modelfile).encode('utf-8')))
            self.create_model_base.set_subtitle(self.convert_model_name(model, 1))
            self.create_model_modelfile_section.set_visible(False)
        else:
            self.create_model_name.set_text(os.path.splitext(os.path.basename(model))[0])
            self.create_model_base.set_subtitle(model)
            self.create_model_modelfile_section.set_visible(True)
        self.navigation_view_manage_models.push_by_tag('model_create_page')

    def show_toast(self, message:str, overlay):
        logger.info(message)
        toast = Adw.Toast(
            title=message,
            timeout=2
        )
        overlay.add_toast(toast)

    def show_notification(self, title:str, body:str, icon:Gio.ThemedIcon=None):
        if not self.is_active() and not self.quick_ask.is_active():
            body = body.replace('<span>', '').replace('</span>', '')
            logger.info(f"{title}, {body}")
            notification = Gio.Notification.new(title)
            notification.set_body(body)
            if icon:
                notification.set_icon(icon)
            self.get_application().send_notification(None, notification)

    def preview_file(self, file_name:str, file_content:str, file_type:str, show_remove:bool):
        logger.info(f"Previewing file: {file_name}")
        if show_remove:
            self.file_preview_remove_button.set_visible(True)
            self.file_preview_remove_button.set_name(file_name)
        else:
            self.file_preview_remove_button.set_visible(False)
        if file_content:
            if file_type == 'image':
                self.file_preview_image.set_visible(True)
                self.file_preview_text_label.set_visible(False)
                image_data = base64.b64decode(file_content)
                loader = GdkPixbuf.PixbufLoader.new()
                loader.write(image_data)
                loader.close()
                pixbuf = loader.get_pixbuf()
                texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                self.file_preview_image.set_from_paintable(texture)
                self.file_preview_image.set_size_request(360, 360)
                self.file_preview_image.set_overflow(1)
                self.file_preview_dialog.set_title(file_name)
                self.file_preview_open_button.set_visible(False)
            else:
                self.file_preview_image.set_visible(False)
                self.file_preview_text_label.set_visible(True)
                buffer = self.file_preview_text_label.set_label(file_content)
                if file_type == 'youtube':
                    self.file_preview_dialog.set_title(file_content.split('\n')[0])
                    self.file_preview_open_button.set_name(file_content.split('\n')[2])
                elif file_type == 'website':
                    self.file_preview_open_button.set_name(file_content.split('\n')[0])
                else:
                    self.file_preview_dialog.set_title(file_name)
                    self.file_preview_open_button.set_visible(False)
            self.file_preview_dialog.present(self)

    def generate_chat_title(self, message, old_chat_name):
        logger.debug("Generating chat title")
        system_prompt = f"""
Generate a title following these rules:
    - The title should be based on the user's prompt
    - Keep it in the same language as the prompt
    - The title needs to be less than 30 characters
    - Use only alphanumeric characters, spaces and optionally emojis
    - Just write the title, NOTHING ELSE
"""
        current_model = self.model_manager.get_selected_model()
        data = {"model": current_model, "messages": [{"role": "system", "content": system_prompt}] + [message], "stream": False}
        try:
            response = self.ollama_instance.request("POST", "api/chat", json.dumps(data))
            if response.status_code == 200:
                new_chat_name = json.loads(response.text)["message"]["content"].strip().removeprefix("Title: ").removeprefix("title: ").strip('\'"').replace('\n', ' ').title().replace('\'S', '\'s')
                new_chat_name = new_chat_name[:50] + (new_chat_name[50:] and '...')
                self.chat_list_box.rename_chat(old_chat_name, new_chat_name)
        except Exception as e:
            logger.error(e)

    def switch_send_stop_button(self, send:bool):
        self.stop_button.set_visible(not send)
        self.send_button.set_visible(send)

    def run_message(self, data:dict, message_element:message_widget.message, chat:chat_widget.chat):
        logger.debug("Running message")
        chat.busy = True
        self.chat_list_box.get_tab_by_name(chat.get_name()).spinner.set_visible(True)
        if [m['role'] for m in data['messages']].count('assistant') == 0 and chat.get_name().startswith(_("New Chat")):
            threading.Thread(target=self.generate_chat_title, args=(data['messages'][0].copy(), chat.get_name())).start()

        if chat.welcome_screen:
            chat.welcome_screen.set_visible(False)
            chat.welcome_screen = None
        if chat.regenerate_button:
            chat.container.remove(chat.regenerate_button)
        self.switch_send_stop_button(False)
        if self.regenerate_button:
            GLib.idle_add(self.chat_list_box.get_current_chat().remove, self.regenerate_button)
        try:
            response = self.ollama_instance.request("POST", "api/chat", json.dumps(data), lambda data, message_element=message_element: message_element.update_message(data))
            if response.status_code != 200:
                raise Exception('Network Error')
        except Exception as e:
            logger.error(e)
            self.chat_list_box.get_tab_by_name(chat.get_name()).spinner.set_visible(False)
            chat.busy = False
            if message_element.spinner:
                GLib.idle_add(message_element.container.remove, message_element.spinner)
                message_element.spinner = None
            GLib.idle_add(message_element.set_text, message_element.content_children[-1].get_label())
            GLib.idle_add(message_element.add_footer, datetime.now())
            GLib.idle_add(chat.show_regenerate_button, message_element)
            sqlite_con = sqlite3.connect(window.sqlite_path)
            cursor = sqlite_con.cursor()
            cursor.execute("UPDATE message SET date_time = ?, content = ? WHERE id = ?",
                (message_element.dt.strftime("%Y/%m/%d %H:%M:%S"), message_element.content_children[-1].get_label(), message_element.message_id)
            )
            sqlite_con.commit()
            sqlite_con.close()
            GLib.idle_add(self.connection_error)

    def load_history(self):
        logger.debug("Loading history")
        sqlite_con = sqlite3.connect(self.sqlite_path)
        cursor = sqlite_con.cursor()
        selected_chat = cursor.execute("SELECT value FROM preferences WHERE id='selected_chat'").fetchone()
        if selected_chat:
            selected_chat = selected_chat[0]
        chats = cursor.execute('SELECT chat.id, chat.name, MAX(message.date_time) AS latest_message_time FROM chat LEFT JOIN message ON chat.id = message.chat_id GROUP BY chat.id ORDER BY latest_message_time DESC').fetchall()
        threads = []
        if len(chats) > 0:
            for row in chats:
                self.chat_list_box.append_chat(row[1], row[0])
                chat_container = self.chat_list_box.get_chat_by_name(row[1])
                if not selected_chat:
                    selected_chat = row[1]
                if row[1] == selected_chat:
                    self.chat_list_box.select_row(self.chat_list_box.tab_list[-1])
                thread = threading.Thread(target=chat_container.load_chat_messages)
                thread.start()
                threads.append(thread)
        else:
            self.chat_list_box.new_chat()
        #for thread in threads:
            #thread.join()
        sqlite_con.close()

    def generate_numbered_name(self, chat_name:str, compare_list:list) -> str:
        if chat_name in compare_list:
            for i in range(len(compare_list)):
                if "." in chat_name:
                    if f"{'.'.join(chat_name.split('.')[:-1])} {i+1}.{chat_name.split('.')[-1]}" not in compare_list:
                        chat_name = f"{'.'.join(chat_name.split('.')[:-1])} {i+1}.{chat_name.split('.')[-1]}"
                        break
                else:
                    if f"{chat_name} {i+1}" not in compare_list:
                        chat_name = f"{chat_name} {i+1}"
                        break
        return chat_name

    def generate_uuid(self) -> str:
        return f"{datetime.today().strftime('%Y%m%d%H%M%S%f')}{uuid.uuid4().hex}"

    def connection_error(self):
        logger.error("Connection error")
        if self.ollama_instance.remote:
            options = {
                _("Close Alpaca"): {"callback": lambda *_: self.get_application().quit(), "appearance": "destructive"},
            }
            if shutil.which('ollama'):
                options[_("Use Local Instance")] = {"callback": lambda *_: self.remote_connection_switch.set_active(False)}
            options[_("Connect")] = {"callback": lambda url, bearer: generic_actions.connect_remote(url,bearer), "appearance": "suggested"}
            entries = [
                {"text": self.ollama_instance.remote_url, "css": ['error'], "placeholder": _('Server URL')},
                {"text": self.ollama_instance.bearer_token, "css": ['error'] if self.ollama_instance.bearer_token else None, "placeholder": _('Bearer Token (Optional)')}
            ]
            dialog_widget.Entry(_('Connection Error'), _('The remote instance has disconnected'), list(options)[0], options, entries)
        else:
            self.ollama_instance.reset()
            self.show_toast(_("There was an error with the local Ollama instance, so it has been reset"), self.main_overlay)

    def get_content_of_file(self, file_path, file_type):
        if not os.path.exists(file_path): return None
        if file_type == 'image':
            try:
                with Image.open(file_path) as img:
                    width, height = img.size
                    max_size = 640
                    if width > height:
                        new_width = max_size
                        new_height = int((max_size / width) * height)
                    else:
                        new_height = max_size
                        new_width = int((max_size / height) * width)
                    resized_img = img.resize((new_width, new_height), Image.LANCZOS)
                    with BytesIO() as output:
                        resized_img.save(output, format="PNG")
                        image_data = output.getvalue()
                    return base64.b64encode(image_data).decode("utf-8")
            except Exception as e:
                logger.error(e)
                self.show_toast(_("Cannot open image"), self.main_overlay)
        elif file_type == 'plain_text' or file_type == 'code' or file_type == 'youtube' or file_type == 'website':
            with open(file_path, 'r', encoding="utf-8") as f:
                return f.read()
        elif file_type == 'pdf':
            reader = PdfReader(file_path)
            if len(reader.pages) == 0:
                return None
            text = ""
            for i, page in enumerate(reader.pages):
                text += f"\n- Page {i}\n{page.extract_text(extraction_mode='layout', layout_mode_space_vertically=False)}\n"
            return text
        elif file_type == 'odt':
            doc = odfopen.load(file_path)
            markdown_elements = []
            for child in doc.text.childNodes:
                if child.qname[1] == 'p' or child.qname[1] == 'span':
                    markdown_elements.append(str(child))
                elif child.qname[1] == 'h':
                    markdown_elements.append('# {}'.format(str(child)))
                elif child.qname[1] == 'table':
                    generated_table = []
                    column_sizes = []
                    for row in child.getElementsByType(odftable.TableRow):
                        generated_table.append([])
                        for column_n, cell in enumerate(row.getElementsByType(odftable.TableCell)):
                            if column_n + 1 > len(column_sizes):
                                column_sizes.append(0)
                            if len(str(cell)) > column_sizes[column_n]:
                                column_sizes[column_n] = len(str(cell))
                            generated_table[-1].append(str(cell))
                    generated_table.insert(1, [])
                    for column_n in range(len(generated_table[0])):
                        generated_table[1].append('-' * column_sizes[column_n])
                    table_str = ''
                    for row in generated_table:
                        for column_n, cell in enumerate(row):
                            table_str += '| {} '.format(cell.ljust(column_sizes[column_n], ' '))
                        table_str += '|\n'
                    markdown_elements.append(table_str)
            return '\n\n'.join(markdown_elements)

    def remove_attached_file(self, name):
        logger.debug("Removing attached file")
        button = self.attachments[name]['button']
        button.get_parent().remove(button)
        del self.attachments[name]
        if len(self.attachments) == 0:
            self.attachment_box.set_visible(False)
        if self.file_preview_dialog.get_visible():
            self.file_preview_dialog.close()

    def attach_file(self, file_path, file_type):
        logger.debug(f"Attaching file: {file_path}")
        file_name = self.generate_numbered_name(os.path.basename(file_path), self.attachments.keys())
        content = self.get_content_of_file(file_path, file_type)
        if content:
            button_content = Adw.ButtonContent(
                label=file_name,
                icon_name={
                    "image": "image-x-generic-symbolic",
                    "plain_text": "document-text-symbolic",
                    "code": "code-symbolic",
                    "pdf": "document-text-symbolic",
                    "odt": "document-text-symbolic",
                    "youtube": "play-symbolic",
                    "website": "globe-symbolic"
                }[file_type]
            )
            button = Gtk.Button(
                vexpand=True,
                valign=0,
                name=file_name,
                css_classes=["flat"],
                tooltip_text=file_name,
                child=button_content
            )
            self.attachments[file_name] = {"path": file_path, "type": file_type, "content": content, "button": button}
            button.connect("clicked", lambda button : self.preview_file(file_name, content, file_type, True))
            self.attachment_container.append(button)
            self.attachment_box.set_visible(True)

    def chat_actions(self, action, user_data):
        chat_row = self.selected_chat_row
        chat_name = chat_row.label.get_label()
        action_name = action.get_name()
        if action_name in ('delete_chat', 'delete_current_chat'):
            dialog_widget.simple(
                _('Delete Chat?'),
                _("Are you sure you want to delete '{}'?").format(chat_name),
                lambda chat_name=chat_name, *_: self.chat_list_box.delete_chat(chat_name),
                _('Delete'),
                'destructive'
            )
        elif action_name in ('duplicate_chat', 'duplicate_current_chat'):
            self.chat_list_box.duplicate_chat(chat_name)
        elif action_name in ('rename_chat', 'rename_current_chat'):
            dialog_widget.simple_entry(
                _('Rename Chat?'),
                _("Renaming '{}'").format(chat_name),
                lambda new_chat_name, old_chat_name=chat_name, *_: self.chat_list_box.rename_chat(old_chat_name, new_chat_name),
                {'placeholder': _('Chat name')},
                _('Rename')
            )
        elif action_name in ('export_chat', 'export_current_chat'):
            chat = self.chat_list_box.get_chat_by_name(chat_name)
            options = {
                _("Importable (.db)"): chat.export_db,
                _("Markdown"): lambda chat=chat: chat.export_md(False),
                _("Markdown (Obsidian Style)"): lambda chat=chat: chat.export_md(True),
                _("JSON"): lambda chat=chat: chat.export_json(False),
                _("JSON (Include Metadata)"): lambda chat=chat: chat.export_json(True)
            }
            dialog_widget.simple_dropdown(
                _("Export Chat"),
                _("Select a method to export the chat"),
                lambda option, options=options: options[option](),
                options.keys()
            )

    def current_chat_actions(self, action, user_data):
        self.selected_chat_row = self.chat_list_box.get_selected_row()
        self.chat_actions(action, user_data)

    def youtube_detected(self, video_url):
        try:
            response = requests.get('https://noembed.com/embed?url={}'.format(video_url))
            data = json.loads(response.text)

            transcriptions = generic_actions.get_youtube_transcripts(data['url'].split('=')[1])
            if len(transcriptions) == 0:
                self.show_toast(_("This video does not have any transcriptions"), self.main_overlay)
                return

            if not any(filter(lambda x: '(en' in x and 'auto-generated' not in x and len(transcriptions) > 1, transcriptions)):
                transcriptions.insert(1, 'English (translate:en)')

            dialog_widget.simple_dropdown(
                _('Attach YouTube Video?'),
                _('{}\n\nPlease select a transcript to include').format(data['title']),
                lambda caption_name, data=data, video_url=video_url: generic_actions.attach_youtube(data['title'], data['author_name'], data['url'], video_url, data['url'].split('=')[1], caption_name),
                transcriptions
            )
        except Exception as e:
            logger.error(e)
            self.show_toast(_("Error attaching video, please try again"), self.main_overlay)

    def cb_text_received(self, text):
        try:
            #Check if text is a Youtube URL
            youtube_regex = re.compile(
                r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/'
                r'(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})')
            url_regex = re.compile(
                r'http[s]?://'
                r'(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|'
                r'(?:%[0-9a-fA-F][0-9a-fA-F]))+'
                r'(?:\\:[0-9]{1,5})?'
                r'(?:/[^\\s]*)?'
            )
            if youtube_regex.match(text):
                self.youtube_detected(text)
            elif url_regex.match(text):
                dialog_widget.simple(
                    _('Attach Website? (Experimental)'),
                    _("Are you sure you want to attach\n'{}'?").format(text),
                    lambda url=text: generic_actions.attach_website(url)
                )
        except Exception as e:
            logger.error(e)

    def cb_image_received(self, clipboard, result):
        try:
            texture = clipboard.read_texture_finish(result)
            if texture:
                if self.model_manager.verify_if_image_can_be_used():
                    pixbuf = Gdk.pixbuf_get_from_texture(texture)
                    if not os.path.exists(os.path.join(cache_dir, 'tmp/images/')):
                        os.makedirs(os.path.join(cache_dir, 'tmp/images/'))
                    image_name = self.generate_numbered_name('image.png', os.listdir(os.path.join(cache_dir, os.path.join(cache_dir, 'tmp/images'))))
                    pixbuf.savev(os.path.join(cache_dir, 'tmp/images/{}'.format(image_name)), "png", [], [])
                    self.attach_file(os.path.join(cache_dir, 'tmp/images/{}'.format(image_name)), 'image')
                else:
                    self.show_toast(_("Image recognition is only available on specific models"), self.main_overlay)
        except Exception as e:
            pass

    def on_file_drop(self, drop_target, value, x, y):
        files = value.get_files()
        for file in files:
            extension = os.path.splitext(file.get_path())[1][1:]
            if extension in ('png', 'jpeg', 'jpg', 'webp', 'gif'):
                self.attach_file(file.get_path(), 'image')
            elif extension in ('txt', 'md'):
                self.attach_file(file.get_path(), 'plain_text')
            elif extension in ("c", "h", "css", "html", "js", "ts", "py", "java", "json", "xml",
                                "asm", "nasm", "cs", "csx", "cpp", "cxx", "cp", "hxx", "inc", "csv",
                                "lsp", "lisp", "el", "emacs", "l", "cu", "dockerfile", "glsl", "g",
                                "lua", "php", "rb", "ru", "rs", "sql", "sh", "p8"):
                self.attach_file(file.get_path(), 'code')
            elif extension == 'pdf':
                self.attach_file(file.get_path(), 'pdf')

    def power_saver_toggled(self, monitor):
        self.banner.set_revealed(monitor.get_power_saver_enabled() and self.powersaver_warning_switch.get_active())

    def remote_switched(self, switch, state):
        def local_instance_process():
            sensitive_elements = [switch, self.tweaks_group, self.instance_page, self.send_button, self.attachment_button]

            [element.set_sensitive(False) for element in sensitive_elements]
            self.get_application().lookup_action('manage_models').set_enabled(False)
            self.title_stack.set_visible_child_name('loading')

            self.ollama_instance.remote = False
            threading.Thread(target=self.ollama_instance.start).start()
            self.model_manager.update_local_list()
            sqlite_con = sqlite3.connect(self.sqlite_path)
            cursor = sqlite_con.cursor()
            cursor.execute("UPDATE preferences SET value=?, type=? WHERE id=?", (False, str(type(False)), "run_remote"))
            sqlite_con.commit()
            sqlite_con.close()

            [element.set_sensitive(True) for element in sensitive_elements]
            self.get_application().lookup_action('manage_models').set_enabled(True)
            self.title_stack.set_visible_child_name('model_selector' if len(self.model_manager.get_model_list()) > 0 else 'no_models')

        if state:
            options = {
                _("Cancel"): {"callback": lambda *_: self.remote_connection_switch.set_active(False)},
                _("Connect"): {"callback": lambda url, bearer: generic_actions.connect_remote(url, bearer), "appearance": "suggested"}
            }
            entries = [
                {"text": self.ollama_instance.remote_url, "placeholder": _('Server URL')},
                {"text": self.ollama_instance.bearer_token, "placeholder": _('Bearer Token (Optional)')}
            ]
            dialog_widget.Entry(
                _('Connect Remote Instance'),
                _('Enter instance information to continue'),
                list(options)[0],
                options,
                entries
            )
        elif self.ollama_instance.remote:
            threading.Thread(target=local_instance_process).start()

    def run_quick_chat(self, data:dict, message_element:message_widget.message):
        try:
            response = self.ollama_instance.request("POST", "api/chat", json.dumps(data), lambda data, message_element=message_element: message_element.update_message(data))
            if response.status_code != 200:
                raise Exception('Network Error')
        except Exception as e:
            logger.error(e)
            self.show_toast(_("An error occurred: {}").format(e), self.quick_ask_overlay)

    def quick_chat(self, message:str):
        self.quick_ask_save_button.set_sensitive(False)
        self.quick_ask.present()
        current_model = self.convert_model_name(self.default_model_list.get_string(self.default_model_combo.get_selected()), 1)
        if current_model is None:
            self.show_toast(_("Please select a model before chatting"), self.quick_ask_overlay)
            return
        chat = chat_widget.chat(_('Quick Ask'), 'QA', True)
        self.quick_ask_overlay.set_child(chat)
        message_id = self.generate_uuid()
        chat.add_message(message_id, None, False)
        m_element = chat.messages[message_id]
        m_element.set_text(message)
        m_element.add_footer(datetime.now())
        data = {
            "model": current_model,
            "messages": chat.convert_to_ollama(),
            "options": {"temperature": self.ollama_instance.tweaks["temperature"]},
            "keep_alive": f"{self.ollama_instance.tweaks['keep_alive']}m",
            "stream": True
        }
        if self.ollama_instance.tweaks["seed"] != 0:
            data['options']['seed'] = self.ollama_instance.tweaks["seed"]
        bot_id=self.generate_uuid()
        chat.add_message(bot_id, current_model, False)
        m_element_bot = chat.messages[bot_id]
        m_element_bot.set_text()
        chat.busy = True
        threading.Thread(target=self.run_quick_chat, args=(data, m_element_bot)).start()

    def prepare_alpaca(self):
        sqlite_con = sqlite3.connect(self.sqlite_path)
        cursor = sqlite_con.cursor()

        configuration = {}
        for row in cursor.execute("SELECT id, value, type FROM preferences").fetchall():
            value = row[1]
            if row[2] == "<class 'int'>":
                value = int(value)
            elif row[2] == "<class 'float'>":
                value = float(value)
            elif row[2] == "<class 'bool'>":
                value = value == "1"
            configuration[row[0]] = value
        if 'show_welcome_dialog' in configuration and configuration['show_welcome_dialog']:
            self.welcome_dialog.present(self)
            sqlite_con.close()
            return

        configuration['model_tweaks'] = {
            "temperature": configuration['temperature'] if 'temperature' in configuration else 0.7,
            "seed": configuration['seed'] if 'seed' in configuration else 0,
            "keep_alive": configuration['keep_alive'] if 'keep_alive' in configuration else 5
        }
        configuration['ollama_overrides'] = {}
        for row in cursor.execute("SELECT id, value FROM overrides"):
            configuration['ollama_overrides'][row[0]] = row[1]

        #Model Manager
        self.model_manager = model_widget.model_manager_container()
        self.model_scroller.set_child(self.model_manager)

        #Chat History
        self.load_history()

        if self.get_application().args.new_chat:
            self.chat_list_box.new_chat(self.get_application().args.new_chat)

        #Instance
        self.ollama_instance = connection_handler.instance(configuration['local_port'], configuration['remote_url'], configuration['run_remote'], configuration['model_tweaks'], configuration['ollama_overrides'], configuration['remote_bearer_token'], configuration['idle_timer'], configuration['model_directory'])

        #Model Manager P.2
        threading.Thread(target=self.model_manager.update_available_list).start()
        threading.Thread(target=self.model_manager.update_local_list).start()

        #User Preferences
        for element in list(list(list(list(self.tweaks_group)[0])[1])[0]):
            if element.get_name() in self.ollama_instance.tweaks:
                element.set_value(self.ollama_instance.tweaks[element.get_name()])

        if configuration['default_model']:
            try:
                for i, model in enumerate(list(self.default_model_list)):
                    if self.convert_model_name(model.get_string(), 1) == configuration['default_model']:
                        self.default_model_combo.set_selected(i)
            except:
                pass

        for element in list(list(list(list(self.overrides_group)[0])[1])[0]):
            if element.get_name() in self.ollama_instance.overrides:
                element.set_text(self.ollama_instance.overrides[element.get_name()])

        self.model_directory_selector.set_subtitle(self.ollama_instance.model_directory)
        self.set_hide_on_close(self.background_switch.get_active())
        self.instance_idle_timer.set_value(self.ollama_instance.idle_timer_delay)
        self.remote_connection_switch.set_active(self.ollama_instance.remote)
        self.remote_connection_switch.get_activatable_widget().connect('state-set', self.remote_switched)
        self.send_button.set_sensitive(True)
        self.attachment_button.set_sensitive(True)
        self.remote_connection_switch.set_visible(shutil.which('ollama'))
        self.remote_connection_selector.set_visible(not shutil.which('ollama'))
        self.tweaks_group.set_sensitive(True)
        self.remote_connection_switch.set_sensitive(True)
        self.instance_page.set_sensitive(shutil.which('ollama') and not self.remote_connection_switch.get_active())
        if not shutil.which('ollama'):
            self.preferences_dialog.remove(self.instance_page)
            self.remote_connection_selector.set_subtitle(configuration['remote_url'])
        self.get_application().lookup_action('manage_models').set_enabled(True)

        if self.get_application().args.ask:
            self.quick_chat(self.get_application().args.ask)

        sqlite_con.close()

    def open_button_menu(self, gesture, x, y, menu):
        button = gesture.get_widget()
        popover = Gtk.PopoverMenu(
            menu_model=menu,
            has_arrow=False,
            halign=1
        )
        position = Gdk.Rectangle()
        position.x = x
        position.y = y
        popover.set_parent(button.get_child())
        popover.set_pointing_to(position)
        popover.popup()

    def setup_sqlite(self):
        if os.path.exists(os.path.join(data_dir, "chats_test.db")) and not os.path.exists(os.path.join(data_dir, "alpaca.db")):
            shutil.move(os.path.join(data_dir, "chats_test.db"), os.path.join(data_dir, "alpaca.db"))
        sqlite_con = sqlite3.connect(self.sqlite_path)
        cursor = sqlite_con.cursor()

        tables = {
            "chat": """
                CREATE TABLE chat (
                    id TEXT NOT NULL PRIMARY KEY,
                    name TEXT NOT NULL
                );
            """,
            "message": """
                CREATE TABLE message (
                    id TEXT NOT NULL PRIMARY KEY,
                    chat_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    model TEXT,
                    date_time DATETIME NOT NULL,
                    content TEXT NOT NULL
                )
            """,
            "attachment": """
                CREATE TABLE attachment (
                    id TEXT NOT NULL PRIMARY KEY,
                    message_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    content TEXT NOT NULL
                )
            """,
            "model": """
                CREATE TABLE model (
                    id TEXT NOT NULL PRIMARY KEY,
                    picture TEXT NOT NULL
                )
            """,
            "preferences": """
                CREATE TABLE preferences (
                    id TEXT NOT NULL PRIMARY KEY,
                    value TEXT,
                    type TEXT
                )
            """,
            "overrides": """
                CREATE TABLE overrides (
                    id TEXT NOT NULL PRIMARY KEY,
                    value TEXT
                )
            """
        }

        for name, script in tables.items():
            if not cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone():
                cursor.execute(script)

        preferences = {
            "remote_url": "http://0.0.0.0:11434",
            "remote_bearer_token": "",
            "run_remote": False,
            "local_port": 11435,
            "run_on_background": False,
            "powersaver_warning": True,
            "default_model": "",
            "idle_timer": 0,
            "model_directory": os.path.join(data_dir, '.ollama', 'models'),
            "selected_chat": None,
            "show_welcome_dialog": True,
            "temperature": 0.7,
            "seed": 0,
            "keep_alive": 5
        }

        for name, value in preferences.items():
            if not cursor.execute("SELECT * FROM preferences WHERE id=?", (name,)).fetchone():
                cursor.execute("INSERT INTO preferences (id, value, type) VALUES (?, ?, ?)", (name, value, str(type(value))))

        sqlite_con.commit()
        sqlite_con.close()

    def initial_convert_to_sql(self):
        if os.path.exists(os.path.join(data_dir, "chats", "chats.json")):
            try:
                with open(os.path.join(data_dir, "chats", "chats.json"), "r", encoding="utf-8") as f:
                    data = json.load(f)
                    sqlite_con = sqlite3.connect(self.sqlite_path)
                    cursor = sqlite_con.cursor()
                    for chat_name in data['chats'].keys():
                        chat_id = self.generate_uuid()
                        cursor.execute("INSERT INTO chat (id, name) VALUES (?, ?);", (chat_id, chat_name))

                        for message_id, message in data['chats'][chat_name]['messages'].items():
                            cursor.execute("INSERT INTO message (id, chat_id, role, model, date_time, content) VALUES (?, ?, ?, ?, ?, ?)",
                            (message_id, chat_id, message['role'], message['model'], message['date'], message['content']))

                            if 'files' in message:
                                for file_name, file_type in message['files'].items():
                                    attachment_id = self.generate_uuid()
                                    content = self.get_content_of_file(os.path.join(data_dir, "chats", chat_name, message_id, file_name), file_type)
                                    cursor.execute("INSERT INTO attachment (id, message_id, type, name, content) VALUES (?, ?, ?, ?, ?)",
                                    (attachment_id, message_id, file_type, file_name, content))
                            if 'images' in message:
                                for image in message['images']:
                                    attachment_id = self.generate_uuid()
                                    content = self.get_content_of_file(os.path.join(data_dir, "chats", chat_name, message_id, image), 'image')
                                    cursor.execute("INSERT INTO attachment (id, message_id, type, name, content) VALUES (?, ?, ?, ?, ?)",
                                    (attachment_id, message_id, 'image', image, content))

                    sqlite_con.commit()
                    sqlite_con.close()
                shutil.move(os.path.join(data_dir, "chats"), os.path.join(data_dir, "chats_OLD"))
            except Exception as e:
                logger.error(e)
                pass

        if os.path.exists(os.path.join(data_dir, "chats")):
            shutil.rmtree(os.path.join(data_dir, "chats"))

        if os.path.exists(os.path.join(config_dir, "server.json")):
            try:
                with open(os.path.join(config_dir, "server.json"), "r", encoding="utf-8") as f:
                    data = json.load(f)
                    sqlite_con = sqlite3.connect(self.sqlite_path)
                    cursor = sqlite_con.cursor()
                    if 'model_tweaks' in data:
                        for name, value in data['model_tweaks'].items():
                            data[name] = value
                        del data['model_tweaks']
                    for name, value in data.items():
                        if isinstance(value, dict) and name == 'ollama_overrides':
                            for name2, value2 in value.items():
                                if cursor.execute("SELECT * FROM overrides WHERE id=?", (name2,)).fetchone():
                                    cursor.execute("UPDATE overrides SET value=? WHERE id=?", (value2, name2))
                                else:
                                    cursor.execute("INSERT INTO overrides (id, value) VALUES (?, ?)", (name2, value2))
                        else:
                            if cursor.execute("SELECT * FROM preferences WHERE id=?", (name,)).fetchone():
                                cursor.execute("UPDATE preferences SET value=?, type=? WHERE id=?", (value, str(type(value)), name))
                            else:
                                cursor.execute("INSERT INTO preferences (id, value, type) VALUES (?, ?, ?)", (name, value, str(type(value))))
                    sqlite_con.commit()
                    sqlite_con.close()
                os.remove(os.path.join(config_dir, "server.json"))
            except Exception as e:
                logger.error(e)
                pass

    def request_screenshot(self):
        bus = SessionBus()
        portal = bus.get("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop")
        subscription = None

        def on_response(sender, obj, iface, signal, *params):
            response = params[0]
            if response[0] == 0:
                uri = response[1].get("uri")
                generic_actions.attach_file(Gio.File.new_for_uri(uri))
            else:
                logger.error(f"Screenshot request failed with response: {response}\n{sender}\n{obj}\n{iface}\n{signal}")
                self.show_toast(_("Attachment failed, screenshot might be too big"), self.main_overlay)
            if subscription:
                subscription.disconnect()

        subscription = bus.subscribe(
            iface="org.freedesktop.portal.Request",
            signal="Response",
            signal_fired=on_response
        )

        portal.Screenshot("", {"interactive": Variant('b', True)})

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        GtkSource.init()
        self.setup_sqlite()
        self.initial_convert_to_sql()
        self.message_searchbar.connect('notify::search-mode-enabled', lambda *_: self.message_search_button.set_active(self.message_searchbar.get_search_mode()))
        message_widget.window = self
        chat_widget.window = self
        model_widget.window = self
        dialog_widget.window = self
        terminal_widget.window = self
        generic_actions.window = self
        connection_handler.window = self

        drop_target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop_target.connect('drop', self.on_file_drop)
        self.message_text_view = GtkSource.View(
            css_classes=['message_text_view'], top_margin=10, bottom_margin=10, hexpand=True
        )

        self.message_text_view_scrolled_window.set_child(self.message_text_view)
        self.message_text_view.add_controller(drop_target)
        self.message_text_view.get_buffer().set_style_scheme(GtkSource.StyleSchemeManager.get_default().get_scheme('adwaita'))
        self.message_text_view.connect('paste-clipboard', self.on_clipboard_paste)

        self.chat_list_box = chat_widget.chat_list()
        self.chat_list_container.set_child(self.chat_list_box)
        enter_key_controller = Gtk.EventControllerKey.new()
        enter_key_controller.connect("key-pressed", lambda controller, keyval, keycode, state: (self.send_message() or True) if keyval==Gdk.KEY_Return and not (state & Gdk.ModifierType.SHIFT_MASK) else None)

        for button, menu in {self.send_button: self.send_message_menu, self.attachment_button: self.attachment_menu}.items():
            gesture_click = Gtk.GestureClick(button=3)
            gesture_click.connect("released", lambda gesture, n_press, x, y, menu=menu: self.open_button_menu(gesture, x, y, menu))
            button.add_controller(gesture_click)
            gesture_long_press = Gtk.GestureLongPress()
            gesture_long_press.connect("pressed", lambda gesture, x, y, menu=menu: self.open_button_menu(gesture, x, y, menu))
            button.add_controller(gesture_long_press)

        self.message_text_view.add_controller(enter_key_controller)
        self.set_help_overlay(self.shortcut_window)
        self.get_application().set_accels_for_action("win.show-help-overlay", ['<primary>slash'])

        universal_actions = {
            'new_chat': [lambda *_: self.chat_list_box.new_chat(), ['<primary>n']],
            'clear': [lambda *i: dialog_widget.simple(_('Clear Chat?'), _('Are you sure you want to clear the chat?'), self.chat_list_box.get_current_chat().clear_chat, _('Clear')), ['<primary>e']],
            'import_chat': [lambda *_: self.chat_list_box.import_chat(), ['<primary>i']],
            'create_model_from_existing': [lambda *i: dialog_widget.simple_dropdown(_('Select Model'), _('This model will be used as the base for the new model'), lambda model: self.create_model(model, False), [self.convert_model_name(model, 0) for model in self.model_manager.get_model_list()])],
            'create_model_from_file': [lambda *i, file_filter=self.file_filter_gguf: dialog_widget.simple_file(file_filter, lambda file: self.create_model(file.get_path(), True))],
            'create_model_from_name': [lambda *i: dialog_widget.simple_entry(_('Pull Model'), _('Input the name of the model in this format\nname:tag'), lambda model: threading.Thread(target=self.model_manager.pull_model, kwargs={"model_name": model}).start(), {'placeholder': 'llama3.2:latest'})],
            'duplicate_chat': [self.chat_actions],
            'duplicate_current_chat': [self.current_chat_actions],
            'delete_chat': [self.chat_actions],
            'delete_current_chat': [self.current_chat_actions],
            'rename_chat': [self.chat_actions],
            'rename_current_chat': [self.current_chat_actions, ['F2']],
            'export_chat': [self.chat_actions],
            'export_current_chat': [self.current_chat_actions],
            'toggle_sidebar': [lambda *_: self.split_view_overlay.set_show_sidebar(not self.split_view_overlay.get_show_sidebar()), ['F9']],
            'manage_models': [lambda *_: self.manage_models_dialog.present(self), ['<primary>m']],
            'search_messages': [lambda *_: self.message_searchbar.set_search_mode(not self.message_searchbar.get_search_mode()), ['<primary>f']],
            'send_message': [lambda *_: self.send_message()],
            'send_system_message': [lambda *_: self.send_message(None, True)],
            'attach_file': [lambda *_, file_filter=self.file_filter_attachments: dialog_widget.simple_file(file_filter, generic_actions.attach_file)],
            'attach_screenshot': [lambda *i: self.request_screenshot() if self.model_manager.verify_if_image_can_be_used() else self.show_toast(_("Image recognition is only available on specific models"), self.main_overlay)],
            'attach_url': [lambda *i: dialog_widget.simple_entry(_('Attach Website? (Experimental)'), _('Please enter a website URL'), self.cb_text_received, {'placeholder': 'https://jeffser.com/alpaca/'})],
            'attach_youtube': [lambda *i: dialog_widget.simple_entry(_('Attach YouTube Captions?'), _('Please enter a YouTube video URL'), self.cb_text_received, {'placeholder': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'})]
        }

        for action_name, data in universal_actions.items():
            self.get_application().create_action(action_name, data[0], data[1] if len(data) > 1 else None)

        self.get_application().lookup_action('manage_models').set_enabled(False)
        self.remote_connection_switch.set_sensitive(False)
        self.tweaks_group.set_sensitive(False)
        self.instance_page.set_sensitive(False)

        self.file_preview_remove_button.connect('clicked', lambda button : dialog_widget.simple(_('Remove Attachment?'), _("Are you sure you want to remove attachment?"), lambda button=button: self.remove_attached_file(button.get_name()), _('Remove'), 'destructive'))
        self.create_model_name.get_delegate().connect("insert-text", lambda *_: self.check_alphanumeric(*_, ['-', '.', '_', ' ']))

        checker = Spelling.Checker.get_default()
        adapter = Spelling.TextBufferAdapter.new(self.message_text_view.get_buffer(), checker)
        self.message_text_view.set_extra_menu(adapter.get_menu_model())
        self.message_text_view.insert_action_group('spelling', adapter)
        adapter.set_enabled(True)
        self.set_focus(self.message_text_view)

        self.prepare_alpaca()

        if self.powersaver_warning_switch.get_active():
            self.banner.set_revealed(Gio.PowerProfileMonitor.dup_default().get_power_saver_enabled())
            
        Gio.PowerProfileMonitor.dup_default().connect("notify::power-saver-enabled", lambda monitor, *_: self.power_saver_toggled(monitor))
        self.banner.connect('button-clicked', lambda *_: self.banner.set_revealed(False))
