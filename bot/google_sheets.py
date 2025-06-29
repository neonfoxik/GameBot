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
        """Записывает данные участников в Лист1 с обновлением только измененных записей
        
        Логика работы:
        1. Получает существующие данные из Лист1
        2. Сравнивает новые данные с существующими по ключу (Дата, Время начала, Участник)
        3. Обновляет только те строки, которые действительно изменились
        4. Добавляет новые записи
        5. Сохраняет неизмененные записи
        6. Перезаписывает лист только при наличии изменений
        """
        if not data:
            return False
        
        try:
            # Сначала получаем существующие данные из Лист1
            existing_data = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range='Лист1!A:K'  # Получаем все данные до колонки K (включая Активность)
            ).execute()
            
            existing_values = existing_data.get('values', [])
            
            # Если есть заголовки, используем их, иначе создаем новые
            if existing_values:
                headers = existing_values[0]
                existing_rows = existing_values[1:]
                
                # Создаем словарь для быстрого поиска существующих записей
                # Новый ключ: (Дата создания, Время начала, Участник)
                existing_records = {}
                for i, row in enumerate(existing_rows):
                    if len(row) >= 2:  # Минимум 2 колонки для ключа
                        key = (row[0], row[4], row[1])  # Дата, Время начала, Участник
                        existing_records[key] = {'index': i, 'row': row}
                
                # Обрабатываем новые данные
                rows_to_update = []
                rows_to_add = []
                rows_to_keep = []
                
                for new_row_data in data:
                    # Создаем ключ для поиска
                    key = (
                        new_row_data['Дата создания'],
                        new_row_data['Время начала'],
                        new_row_data['Участник']
                    )
                    
                    # Формируем новую строку
                    new_row = []
                    for header in headers:
                        new_row.append(str(new_row_data.get(header, '')))
                    
                    if key in existing_records:
                        # Проверяем, изменились ли данные
                        existing_row = existing_records[key]['row']
                        row_changed = False
                        
                        # Сравниваем строки по всем колонкам
                        for i, (existing_val, new_val) in enumerate(zip(existing_row, new_row)):
                            if existing_val != new_val:
                                row_changed = True
                                break
                        
                        # Если данные изменились, обновляем строку
                        if row_changed:
                            row_index = existing_records[key]['index']
                            rows_to_update.append((row_index + 2, new_row))  # +2 потому что индексация с 1 и есть заголовок
                            print(f"Найдены изменения в записи: {new_row[1]} ({new_row[4]}-{new_row[5]})")
                        else:
                            # Данные не изменились, сохраняем существующую строку
                            rows_to_keep.append(existing_row)
                            print(f"Запись не изменилась: {new_row[1]} ({new_row[4]}-{new_row[5]})")
                    else:
                        # Добавляем новую запись
                        rows_to_add.append(new_row)
                        print(f"Новая запись: {new_row[1]} ({new_row[4]}-{new_row[5]})")
                
                # Добавляем все существующие записи, которые не были обработаны
                for i, row in enumerate(existing_rows):
                    key = (row[0], row[4], row[1]) if len(row) >= 2 else None
                    if key:
                        # Проверяем, была ли эта запись обработана в новых данных
                        was_processed = False
                        for new_row_data in data:
                            new_key = (new_row_data['Дата создания'], new_row_data['Время начала'], new_row_data['Участник'])
                            if key == new_key:
                                was_processed = True
                                break
                        
                        if not was_processed:
                            rows_to_keep.append(row)
                
                # Обновляем измененные записи
                for row_index, new_row in rows_to_update:
                    range_name = f'Лист1!A{row_index}:K{row_index}'
                    self.service.spreadsheets().values().update(
                        spreadsheetId=self.spreadsheet_id,
                        range=range_name,
                        valueInputOption="RAW",
                        body={"values": [new_row]}
                    ).execute()
                    print(f"Обновлена существующая запись в строке {row_index}: {new_row[1]} ({new_row[4]}-{new_row[5]})")
                
                # Формируем финальный список всех строк
                all_rows = rows_to_keep + rows_to_add
                
                # Если есть новые записи, добавляем их в конец
                if rows_to_add:
                    if all_rows:
                        # Добавляем новые записи к существующим
                        self.service.spreadsheets().values().append(
                            spreadsheetId=self.spreadsheet_id,
                            range='Лист1!A:K',
                            valueInputOption="RAW",
                            insertDataOption="INSERT_ROWS",
                            body={"values": rows_to_add}
                        ).execute()
                    else:
                        # Если нет существующих записей, создаем новые
                        all_rows = rows_to_add
                
                # Если есть изменения, перезаписываем весь лист
                if rows_to_update or rows_to_add:
                    if all_rows:
                        final_values = [headers] + all_rows
                        self.service.spreadsheets().values().update(
                            spreadsheetId=self.spreadsheet_id,
                            range='Лист1!A1',
                            valueInputOption="RAW",
                            body={"values": final_values}
                        ).execute()
                
                # После записи данных добавить вызов self._colorize_events_in_sheet1(headers, all_rows)
                self._colorize_events_in_sheet1(headers, all_rows)
                
                print(f"Всего обработано записей: {len(data)}, обновлено: {len(rows_to_update)}, добавлено: {len(rows_to_add)}, сохранено: {len(rows_to_keep)}")
            
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
        """Удаляет данные конкретной активности из Лист1"""
        try:
            # Получаем все данные из Лист1
            existing_data = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range='Лист1!A:K'
            ).execute()
            
            existing_values = existing_data.get('values', [])
            
            if not existing_values:
                return True  # Лист пустой, нечего удалять
            
            headers = existing_data[0]
            data_rows = existing_data[1:]
            
            # Находим строки, которые нужно удалить
            rows_to_keep = []
            activity_date = activity_history.activity_started_at.strftime('%d.%m.%Y')
            activity_name = activity_history.name
            
            for i, row in enumerate(data_rows):
                if len(row) > 0:
                    # Проверяем, не относится ли эта строка к удаляемой активности
                    # Сравниваем по дате создания (первая колонка) и названию активности
                    if len(row) >= 1 and row[0] == activity_date:
                        # Проверяем, есть ли в строке название активности
                        if len(row) >= 11 and 'Активность' in headers:
                            # Если есть колонка "Активность", сравниваем по ней
                            activity_col_index = headers.index('Активность')
                            if len(row) > activity_col_index and row[activity_col_index] == activity_name:
                                # Это строка нашей активности - пропускаем её
                                print(f"Удаляем запись активности: {row[1]} ({activity_name})")
                                continue
                        else:
                            # Если нет колонки с названием активности, удаляем все записи с этой датой
                            # но только если это единственная активность с этой датой
                            print(f"Удаляем запись с датой {activity_date}: {row[1]}")
                            continue
                    
                    # Это строка другой активности - сохраняем её
                    rows_to_keep.append(row)
            
            # Если все строки удалены, очищаем лист
            if not rows_to_keep:
                # Очищаем весь лист
                self.service.spreadsheets().values().clear(
                    spreadsheetId=self.spreadsheet_id,
                    range='Лист1!A:K'
                ).execute()
                print(f"Удалены все записи активности '{activity_name}' с даты {activity_date}")
            else:
                # Записываем оставшиеся данные
                new_values = [headers] + rows_to_keep
                self.service.spreadsheets().values().update(
                    spreadsheetId=self.spreadsheet_id,
                    range='Лист1!A1',
                    valueInputOption="RAW",
                    body={"values": new_values}
                ).execute()
                print(f"Удалены записи активности '{activity_name}' с даты {activity_date}, сохранено {len(rows_to_keep)} других записей")
            
            return True
            
        except HttpError as error:
            print(f"Ошибка при удалении данных активности из Лист1: {error}")
            return False 

    def _colorize_events_in_sheet1(self, headers, all_rows):
        """Чередует цвет строк для разных событий активности (название + дата/время)"""
        try:
            # Получаем sheetId для Лист1
            spreadsheet = self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
            sheet_id = None
            for sheet in spreadsheet['sheets']:
                if sheet['properties']['title'] == 'Лист1':
                    sheet_id = sheet['properties']['sheetId']
                    break
            if sheet_id is None:
                return
            
            # Находим индексы нужных колонок
            activity_col_index = None
            date_col_index = None
            for i, header in enumerate(headers):
                if header == 'Активность':
                    activity_col_index = i
                elif header == 'Дата создания':
                    date_col_index = i
            
            if activity_col_index is None or date_col_index is None:
                print("Колонки 'Активность' или 'Дата создания' не найдены")
                return
            
            # Группируем строки по уникальным событиям (название активности + дата/время)
            event_groups = {}  # {(название_активности, дата_время): [индексы_строк]}
            for i, row in enumerate(all_rows):
                if len(row) > max(activity_col_index, date_col_index):
                    activity_name = row[activity_col_index]
                    date_time = row[date_col_index]
                    event_key = (activity_name, date_time)
                    
                    if event_key not in event_groups:
                        event_groups[event_key] = []
                    event_groups[event_key].append(i)
            
            # Цвета для чередования событий
            colors = [
                {"red": 1, "green": 0.95, "blue": 0.5},  # банановый
                {"red": 0.7, "green": 0.9, "blue": 1}    # нежно-голубой
            ]
            
            requests = []
            color_index = 0
            
            # Окрашиваем каждое уникальное событие своим цветом
            for event_key, row_indices in event_groups.items():
                activity_name, date_time = event_key
                color = colors[color_index % 2]
                
                for row_idx in row_indices:
                    # +2 потому что индексация с 1 и есть заголовок
                    actual_row = row_idx + 2
                    
                    requests.append({
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": actual_row - 1,  # Google Sheets использует 0-индексацию
                                "endRowIndex": actual_row
                            },
                            "cell": {"userEnteredFormat": {"backgroundColor": color}},
                            "fields": "userEnteredFormat.backgroundColor"
                        }
                    })
                
                color_index += 1
                print(f"Событие '{activity_name}' от {date_time} окрашено в цвет {color_index % 2 + 1}")
            
            if requests:
                self.service.spreadsheets().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={"requests": requests}
                ).execute()
                print(f"Окрашено {len(requests)} строк для {len(event_groups)} уникальных событий")
                
        except Exception as e:
            print(f"Ошибка при окрашивании строк: {e}") 