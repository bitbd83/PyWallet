#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import re
from threading import Thread

import kivy
from ethereum.utils import normalize_address
from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.metrics import dp
from kivy.properties import NumericProperty, ObjectProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.utils import platform
from kivymd.button import MDIconButton
from kivymd.dialog import MDDialog
from kivymd.label import MDLabel
from kivymd.list import ILeftBodyTouch, OneLineListItem, TwoLineIconListItem
from kivymd.snackbar import Snackbar
from kivymd.textfields import MDTextField
from kivymd.theming import ThemeManager
from requests.exceptions import ConnectionError

from pywalib import PyWalib

kivy.require('1.10.0')


class IconLeftWidget(ILeftBodyTouch, MDIconButton):
    pass


class FloatInput(MDTextField):
    """
    Accepts float numbers only.
    """

    pat = re.compile('[^0-9]')

    def insert_text(self, substring, from_undo=False):
        pat = self.pat
        if '.' in self.text:
            s = re.sub(pat, '', substring)
        else:
            s = '.'.join([re.sub(pat, '', s) for s in substring.split('.', 1)])
        return super(FloatInput, self).insert_text(s, from_undo=from_undo)


class PasswordForm(BoxLayout):

    password = StringProperty()

    def __init__(self, **kwargs):
        super(PasswordForm, self).__init__(**kwargs)


class Send(BoxLayout):

    password = StringProperty("")
    send_to_address = StringProperty("")
    send_amount = NumericProperty(0)

    def __init__(self, **kwargs):
        super(Send, self).__init__(**kwargs)

    def verify_to_address_field(self):
        title = "Input error"
        body = "Invalid address field"
        try:
            normalize_address(self.send_to_address)
        except Exception:
            dialog = Controller.create_dialog(title, body)
            dialog.open()
            return False
        return True

    def verify_amount_field(self):
        title = "Input error"
        body = "Invalid amount field"
        if self.send_amount == 0:
            dialog = Controller.create_dialog(title, body)
            dialog.open()
            return False
        return True

    def verify_fields(self):
        """
        Verifies address and amount fields are valid.
        """
        return self.verify_to_address_field() \
            and self.verify_amount_field()

    def on_unlock_clicked(self, dialog, password):
        self.password = password
        dialog.dismiss()

    @staticmethod
    def show_invalid_form_dialog():
        title = "Invalid form"
        body = "Please check form fields."
        dialog = Controller.create_dialog(title, body)
        dialog.open()

    def prompt_password_dialog(self):
        """
        Prompt the password dialog.
        """
        title = "Enter your password"
        content = PasswordForm()
        dialog = MDDialog(
                        title=title,
                        content=content,
                        size_hint=(.8, None),
                        height=dp(250),
                        auto_dismiss=False)
        # workaround for MDDialog container size (too small by default)
        dialog.ids.container.size_hint_y = 1
        dialog.add_action_button(
                "Unlock",
                action=lambda *x: self.on_unlock_clicked(
                    dialog, content.password))
        return dialog

    def on_send_click(self):
        if not self.verify_fields():
            Send.show_invalid_form_dialog()
            return
        dialog = self.prompt_password_dialog()
        dialog.open()

    @mainthread
    def snackbar_message(self, text):
        Snackbar(text=text).show()

    def unlock_send_transaction(self):
        """
        Unlocks the account with password in order to sign and publish the
        transaction.
        """
        controller = App.get_running_app().controller
        pywalib = controller.pywalib
        address = normalize_address(self.send_to_address)
        amount_eth = self.send_amount
        amount_wei = int(amount_eth * pow(10, 18))
        account = controller.pywalib.get_main_account()
        self.snackbar_message("Unlocking account...")
        try:
            account.unlock(self.password)
        except ValueError:
            self.snackbar_message("Could not unlock account")
            return

        self.snackbar_message("Unlocked! Sending transaction...")
        sender = account.address
        pywalib.transact(address, value=amount_wei, data='', sender=sender)
        self.snackbar_message("Sent!")

    def _start_unlock_send_transaction_thread(self):
        """
        Runs unlock_send_transaction() in a thread.
        """
        thread = Thread(target=self.unlock_send_transaction)
        thread.start()

    def on_password(self, instance, password):
        self._start_unlock_send_transaction_thread()


class Receive(BoxLayout):

    current_account = ObjectProperty(None, allownone=True)
    current_account_string = StringProperty()

    def __init__(self, **kwargs):
        super(Receive, self).__init__(**kwargs)
        Clock.schedule_once(lambda dt: self.setup())

    def setup(self):
        """
        Default state setup.
        """
        self.controller = App.get_running_app().controller
        self.current_account = self.controller.pywalib.get_main_account()

    def show_address(self, address):
        self.ids.qr_code_id.data = address

    def on_current_account_string(self, instance, address):
        self.show_address(address)

    def on_current_account(self, instance, account):
        address = "0x" + account.address.encode("hex")
        self.current_account_string = address

    def open_account_list(self):
        def on_selected_item(instance, value):
            self.current_account = value.account
        self.controller.open_account_list_helper(on_selected_item)


class History(BoxLayout):

    current_account = ObjectProperty(None, allownone=True)

    def on_current_account(self, instance, account):
        print("History.on_current_account:")
        self._start_load_history_thread()

    @staticmethod
    def create_item(sent, amount, from_to):
        """
        Creates a history list item from parameters.
        """
        send_receive = "Sent" if sent else "Received"
        text = "%s %sETH" % (send_receive, amount)
        secondary_text = from_to
        icon = "arrow-up-bold" if sent else "arrow-down-bold"
        list_item = TwoLineIconListItem(
            text=text, secondary_text=secondary_text)
        icon_widget = IconLeftWidget(icon=icon)
        list_item.add_widget(icon_widget)
        return list_item

    @staticmethod
    def create_item_from_dict(transaction_dict):
        """
        Creates a history list item from a transaction dictionary.
        """
        extra_dict = transaction_dict['extra_dict']
        sent = extra_dict['sent']
        amount = extra_dict['value_eth']
        from_address = extra_dict['from_address']
        to_address = extra_dict['to_address']
        from_to = to_address if sent else from_address
        list_item = History.create_item(sent, amount, from_to)
        return list_item

    @mainthread
    def update_history_list(self, list_items):
        history_list_id = self.ids.history_list_id
        history_list_id.clear_widgets()
        for list_item in list_items:
            history_list_id.add_widget(list_item)

    def _load_history(self):
        account = self.current_account
        address = '0x' + account.address.encode("hex")
        print("History._load_history address:", address)
        try:
            transactions = PyWalib.get_transaction_history(address)
        except ConnectionError:
            Controller.on_history_connection_error()
            return
        list_items = []
        for transaction in transactions:
            list_item = History.create_item_from_dict(transaction)
            list_items.append(list_item)
        self.update_history_list(list_items)

    def _start_load_history_thread(self):
        """
        Runs _load_history() in a thread.
        """
        load_history_thread = Thread(target=self._load_history)
        load_history_thread.start()


class Overview(BoxLayout):

    current_account = ObjectProperty(None, allownone=True)
    current_account_string = StringProperty()

    def on_current_account(self, instance, account):
        address = "0x" + account.address.encode("hex")
        self.current_account_string = address

    def open_account_list(self):
        controller = App.get_running_app().controller
        controller.open_account_list_overview()


class PWSelectList(BoxLayout):

    selected_item = ObjectProperty()

    def __init__(self, **kwargs):
        self._items = kwargs.pop('items')
        super(PWSelectList, self).__init__(**kwargs)
        self._setup()

    def on_release(self, item):
        self.selected_item = item

    def _setup(self):
        address_list = self.ids.address_list_id
        for item in self._items:
            item.bind(on_release=lambda x: self.on_release(x))
            address_list.add_widget(item)


class Controller(FloatLayout):

    current_account = ObjectProperty(None, allownone=True)

    def __init__(self, **kwargs):
        super(Controller, self).__init__(**kwargs)
        keystore_path = Controller.get_keystore_path()
        self.pywalib = PyWalib(keystore_path)
        # will trigger account data fetching
        self.current_account = self.pywalib.get_main_account()

    @property
    def overview(self):
        return self.ids.overview_id

    @property
    def history(self):
        return self.overview.ids.history_id

    def open_account_list_helper(self, on_selected_item):
        title = "Select account"
        items = []
        pywalib = self.pywalib
        account_list = pywalib.get_account_list()
        for account in account_list:
            address = '0x' + account.address.encode("hex")
            item = OneLineListItem(text=address)
            item.account = account
            items.append(item)
        dialog = Controller.create_list_dialog(
            title, items, on_selected_item)
        dialog.open()

    def open_account_list_overview(self):
        def on_selected_item(instance, value):
            self.set_current_account(value.account)
        self.open_account_list_helper(on_selected_item)

    def set_current_account(self, account):
        self.current_account = account

    def on_current_account(self, instance, value):
        """
        Updates Overview.current_account and History.current_account,
        then fetch account data.
        """
        self.overview.current_account = value
        self.history.current_account = value
        self._start_load_balance_thread()

    @staticmethod
    def get_keystore_path():
        """
        This is the Kivy default keystore path.
        """
        default_keystore_path = PyWalib.get_default_keystore_path()
        if platform != "android":
            return default_keystore_path
        # makes sure the leading slash gets removed
        default_keystore_path = default_keystore_path.strip('/')
        user_data_dir = App.get_running_app().user_data_dir
        # preprends with kivy user_data_dir
        keystore_path = os.path.join(
            user_data_dir, default_keystore_path)
        return keystore_path

    @staticmethod
    def create_list_dialog(title, items, on_selected_item):
        """
        Creates a dialog from given title and list.
        items is a list of BaseListItem objects.
        """
        # select_list = PWSelectList(items=items, on_release=on_release)
        select_list = PWSelectList(items=items)
        select_list.bind(selected_item=on_selected_item)
        content = select_list
        dialog = MDDialog(
                        title=title,
                        content=content,
                        size_hint=(.8, .8))
        # workaround for MDDialog container size (too small by default)
        dialog.ids.container.size_hint_y = 1
        # close the dialog as we select the element
        select_list.bind(
            selected_item=lambda instance, value: dialog.dismiss())
        dialog.add_action_button(
                "Dismiss",
                action=lambda *x: dialog.dismiss())
        return dialog

    @staticmethod
    def create_dialog(title, body):
        """
        Creates a dialog from given title and body.
        """
        content = MDLabel(
                    font_style='Body1',
                    theme_text_color='Secondary',
                    text=body,
                    size_hint_y=None,
                    valign='top')
        content.bind(texture_size=content.setter('size'))
        dialog = MDDialog(
                        title=title,
                        content=content,
                        size_hint=(.8, None),
                        height=dp(200),
                        auto_dismiss=False)
        dialog.add_action_button(
                "Dismiss",
                action=lambda *x: dialog.dismiss())
        return dialog

    @staticmethod
    def on_balance_connection_error():
        title = "Network error"
        body = "Couldn't load balance, no network access."
        dialog = Controller.create_dialog(title, body)
        dialog.open()

    @staticmethod
    def on_history_connection_error():
        title = "Network error"
        body = "Couldn't load history, no network access."
        dialog = Controller.create_dialog(title, body)
        dialog.open()

    @staticmethod
    def show_not_implemented_dialog():
        title = "Not implemented"
        body = "This feature is not yet implemented."
        dialog = Controller.create_dialog(title, body)
        dialog.open()

    @mainthread
    def update_balance_label(self, balance):
        overview_id = self.ids.overview_id
        balance_label_id = overview_id.ids.balance_label_id
        balance_label_id.text = '%s ETH' % balance

    def _load_landing_page(self, dt=None):
        """
        Loads the landing page.
        """
        try:
            self._load_balance()
        except IndexError:
            self._load_manage_keystores()

    def _load_balance(self):
        account = self.current_account
        try:
            balance = self.pywalib.get_balance(account.address.encode("hex"))
        except ConnectionError:
            Controller.on_balance_connection_error()
            return
        self.update_balance_label(balance)

    def _start_load_balance_thread(self):
        """
        Runs _load_balance() in a thread.
        """
        load_balance_thread = Thread(target=self._load_balance)
        load_balance_thread.start()

    def _load_manage_keystores(self):
        """
        Loads the manage keystores screen.
        """
        self.ids.screen_manager_id.current = 'manage_keystores'


class ControllerApp(App):
    theme_cls = ThemeManager()

    def __init__(self, **kwargs):
        super(ControllerApp, self).__init__(**kwargs)
        self._controller = None

    def build(self):
        self._controller = Controller(info='PyWallet')
        return self._controller

    @property
    def controller(self):
        return self._controller


if __name__ == '__main__':
    ControllerApp().run()