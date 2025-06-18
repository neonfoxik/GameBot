import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime

class GoogleSheetsManager:
    def __init__(self):
        # Путь к файлу service account
        creds_path = os.getenv('GOOGLE_SHEETS_CREDS', 'google-credentials.json')
        self.spreadsheet_id = os.getenv('GOOGLE_SHEETS_ID')
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        self.creds = service_account.Credentials.from_service_account_file(creds_path, scopes=scopes)
        self.service = build('sheets', 'v4', credentials=self.creds)

    def get_spreadsheet_url(self):
        """Возвращает URL таблицы"""
        return f"https://docs.google.com/spreadsheets/d/{self.spreadsheet_id}"

    def create_activity_sheet(self, activity_name):
        """Создаёт новый лист с названием активности и датой (например, 'ИмяАктивности (01.06.2024)')"""
        date_str = datetime.now().strftime('%d.%m.%Y')
        sheet_title = f"{activity_name} ({date_str})"
        try:
            requests = [{
                'addSheet': {
                    'properties': {
                        'title': sheet_title
                    }
                }
            }]
            body = {'requests': requests}
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body=body
            ).execute()
            return sheet_title
        except HttpError as error:
            print(f"Ошибка при создании листа: {error}")
            return None

    def write_activity_data(self, sheet_title, data):
        """Записывает данные участников в указанный лист"""
        if not data:
            return False
        # Формируем заголовки и строки
        headers = list(data[0].keys())
        values = [headers] + [[row[h] for h in headers] for row in data]
        try:
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{sheet_title}'!A1",
                valueInputOption="RAW",
                body={"values": values}
            ).execute()
            return True
        except HttpError as error:
            print(f"Ошибка при записи данных: {error}")
            return False

    def delete_sheet(self, sheet_title):
        """Удаляет лист из таблицы"""
        try:
            spreadsheet = self.service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id
            ).execute()
            sheet_id = None
            for sheet in spreadsheet['sheets']:
                if sheet['properties']['title'] == sheet_title:
                    sheet_id = sheet['properties']['sheetId']
                    break
            if not sheet_id:
                print(f"Лист '{sheet_title}' не найден")
                return False
            request = {
                'deleteSheet': {
                    'sheetId': sheet_id
                }
            }
            body = {
                'requests': [request]
            }
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body=body
            ).execute()
            return True
        except HttpError as error:
            print(f"Ошибка при удалении листа: {error}")
            return False 