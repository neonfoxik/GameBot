import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime, timedelta

class GoogleSheetsManager:
    def __init__(self):
        creds_json = os.getenv('GOOGLE_SHEETS_CREDS_JSON')
        if not creds_json:
            raise ValueError("Не найдена переменная окружения GOOGLE_SHEETS_CREDS_JSON")
        try:
            creds_info = json.loads(creds_json)
        except Exception as e:
            raise ValueError(f"Ошибка парсинга GOOGLE_SHEETS_CREDS_JSON: {e}")
        self.spreadsheet_id = os.getenv('GOOGLE_SHEETS_ID')
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        self.creds = service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)
        self.service = build('sheets', 'v4', credentials=self.creds)

    def get_spreadsheet_url(self):
        """Возвращает URL таблицы"""
        return f"https://docs.google.com/spreadsheets/d/{self.spreadsheet_id}"

    def create_activity_sheet(self, activity_name):
        """Создаёт новый лист с названием активности, датой и временем (например, 'ИмяАктивности (01.06.2024 22:41)')"""
        date_str = (datetime.now() + timedelta(hours=3)).strftime('%d.%m.%Y %H:%M')
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

    def write_activity_data_to_sheet1(self, data):
        """Записывает данные участников в Лист1 с заменой существующих записей"""
        if not data:
            return False
        
        try:
            # Сначала получаем существующие данные из Лист1
            existing_data = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range='Лист1!A:J'  # Получаем все данные до колонки J
            ).execute()
            
            existing_values = existing_data.get('values', [])
            
            # Если есть заголовки, используем их, иначе создаем новые
            if existing_values:
                headers = existing_values[0]
                existing_rows = existing_values[1:]
                
                # Создаем словарь для быстрого поиска существующих записей
                # Ключ: (Дата создания, Участник, Время начала, Время конца)
                existing_records = {}
                for i, row in enumerate(existing_rows):
                    if len(row) >= 5:  # Минимум 5 колонок для ключа
                        key = (row[0], row[1], row[4], row[5])  # Дата, Участник, Время начала, Время конца
                        existing_records[key] = i
                
                # Обрабатываем новые данные
                rows_to_update = []
                rows_to_add = []
                
                for new_row_data in data:
                    # Создаем ключ для поиска
                    key = (
                        new_row_data['Дата создания'],
                        new_row_data['Участник'],
                        new_row_data['Время начала'],
                        new_row_data['Время конца']
                    )
                    
                    # Формируем новую строку
                    new_row = []
                    for header in headers:
                        new_row.append(str(new_row_data.get(header, '')))
                    
                    if key in existing_records:
                        # Заменяем существующую запись
                        row_index = existing_records[key]
                        rows_to_update.append((row_index + 2, new_row))  # +2 потому что индексация с 1 и есть заголовок
                    else:
                        # Добавляем новую запись
                        rows_to_add.append(new_row)
                
                # Обновляем существующие записи
                for row_index, new_row in rows_to_update:
                    range_name = f'Лист1!A{row_index}:J{row_index}'
                    self.service.spreadsheets().values().update(
                        spreadsheetId=self.spreadsheet_id,
                        range=range_name,
                        valueInputOption="RAW",
                        body={"values": [new_row]}
                    ).execute()
                    print(f"Обновлена существующая запись в строке {row_index}: {new_row[1]} ({new_row[4]}-{new_row[5]})")
                
                # Добавляем новые записи в конец
                if rows_to_add:
                    self.service.spreadsheets().values().append(
                        spreadsheetId=self.spreadsheet_id,
                        range='Лист1!A:J',
                        valueInputOption="RAW",
                        insertDataOption="INSERT_ROWS",
                        body={"values": rows_to_add}
                    ).execute()
                    print(f"Добавлено {len(rows_to_add)} новых записей в Google Sheets")
                
                print(f"Всего обработано записей: {len(data)}, обновлено: {len(rows_to_update)}, добавлено: {len(rows_to_add)}")
            
            else:
                # Если лист пустой, создаем заголовки и данные
                headers = list(data[0].keys())
                values = [headers] + [[row[h] for h in headers] for row in data]
                
                self.service.spreadsheets().values().update(
                    spreadsheetId=self.spreadsheet_id,
                    range='Лист1!A1',
                    valueInputOption="RAW",
                    body={"values": values}
                ).execute()
            
            return True
            
        except HttpError as error:
            print(f"Ошибка при записи данных в Лист1: {error}")
            return False

    def delete_activity_data_from_sheet1(self, activity_history):
        """Удаляет данные активности из Лист1"""
        try:
            # Получаем все данные из Лист1
            existing_data = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range='Лист1!A:J'
            ).execute()
            
            existing_values = existing_data.get('values', [])
            
            if not existing_values:
                return True  # Лист пустой, нечего удалять
            
            headers = existing_data[0]
            data_rows = existing_data[1:]
            
            # Находим строки, которые нужно удалить
            rows_to_keep = []
            activity_date = activity_history.activity_started_at.strftime('%d.%m.%Y')
            
            for i, row in enumerate(data_rows):
                if len(row) > 0:
                    # Проверяем, не относится ли эта строка к удаляемой активности
                    # Сравниваем по дате создания (первая колонка)
                    if len(row) >= 1 and row[0] == activity_date:
                        # Это строка нашей активности - пропускаем её
                        continue
                    else:
                        # Это строка другой активности - сохраняем её
                        rows_to_keep.append(row)
            
            # Если все строки удалены, очищаем лист
            if not rows_to_keep:
                # Очищаем весь лист
                self.service.spreadsheets().values().clear(
                    spreadsheetId=self.spreadsheet_id,
                    range='Лист1!A:J'
                ).execute()
            else:
                # Записываем оставшиеся данные
                new_values = [headers] + rows_to_keep
                self.service.spreadsheets().values().update(
                    spreadsheetId=self.spreadsheet_id,
                    range='Лист1!A1',
                    valueInputOption="RAW",
                    body={"values": new_values}
                ).execute()
            
            return True
            
        except HttpError as error:
            print(f"Ошибка при удалении данных активности из Лист1: {error}")
            return False 