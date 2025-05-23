import aiocache
from datetime import datetime, timedelta

from .requests import get_work_schedule
from api.v3.constants import SCHEDULE_ID


COMMON_HOLIDAYS = set(("01.01", "02.01", "07.01", "23.02", "08.03", "01.05", "09.05", "12.06", "04.11"))


class Schedule:
    """За битрикс реализуем рабочий календарь"""

    def __init__(self):
        self.exclusions = COMMON_HOLIDAYS.copy()
        self.work_days = '12345'
        self.work_time_start = timedelta(seconds=32_400)
        self.work_time_end = timedelta(seconds=64_800)
        self.work_day_duration = timedelta(seconds=32_400)
    
    @staticmethod
    def split_timedelta(td: timedelta) -> tuple[int, int, int]:
        """
        Разбивает объект timedelta на часы, минуты и секунды.
        Если присутсвуют микросекунды, то они будут отброшены.
        """
        seconds_in_delta = int(td.total_seconds())
        hours = seconds_in_delta // 3600
        minutes = (seconds_in_delta % 3600) // 60
        seconds = seconds_in_delta % 60
        return hours, minutes, seconds
    
    def is_working_time(self, dt: datetime) -> bool:
        """
        Проверяет, что переданный объект datetime находится в промежутках рабочего времени.
        """
        if dt.strftime(r"%d.%m") in self.exclusions:
            return False
        if dt.strftime("%w") not in self.work_days:
            return False
        time_from_dt = timedelta(hours=dt.hour, minutes=dt.minute, seconds=dt.second)
        return self.work_time_start <= time_from_dt < self.work_time_end

    def get_nearest_datetime(self, dt: datetime) -> datetime:
        """Получает ближайшеий объект datetime, который находится в промежутке рабочего времени, к указанному dt"""
        if self.is_working_time(dt):
            return dt
        total_seconds = int(self.work_time_start.total_seconds())
        hour = total_seconds // 3600
        minute = (total_seconds % 3600) // 60
        second = total_seconds % 60
        dt = dt.replace(hour=hour, minute=minute, second=second) + timedelta(days=1)
        while not self.is_working_time(dt):
            dt += timedelta(days=1)
        return dt

    def _add_duration(self, start: datetime, duration: int | timedelta) -> datetime:
        """Прибавляет к start duration - время в секундах (или готовый объект timedelta) c учетом рабочего времени."""
        if isinstance(duration, (int, float)):
            duration = timedelta(seconds=duration)
        dt = self.get_nearest_datetime(start)
        delta_0 = timedelta(seconds=0)
        minute = timedelta(minutes=1)
        while duration > delta_0:
            to_add = minute if minute < duration else duration
            dt += to_add
            if self.is_working_time(dt):
                duration -= to_add
        return dt

    def add_duration(self, start: datetime, duration: int | timedelta) -> datetime:
        """
        Прибавляет к start duration - время в секундах (или готовый объект timedelta) c учетом рабочего времени.
        Если результат равен 9:00, то откатывает до 18:00 предыдущего рабочего дня.
        """
        result = self._add_duration(start, duration)
        result_delta = timedelta(hours=result.hour, minutes=result.minute, seconds=result.second)
        if result_delta == self.work_time_start:
            while True:
                result -= timedelta(days=1)
                if self.is_working_time(result):
                    break
            hour, minute, second = self.split_timedelta(self.work_time_end)
            result = result.replace(hour=hour, minute=minute, second=second)
        return result
    
    def get_duration(self, start: datetime, end: datetime) -> timedelta:
        """Высчитывает продолжительность рабочего времени между start и end"""
        minute = timedelta(minutes=1)
        duration = timedelta(minutes=0)
        while start < end:
            if self.is_working_time(start):
                duration += minute
            start += minute
        return duration
    

work_schedule_cache = aiocache.cached(ttl=60 * 60 * 24, namespace="work_schedule")

@work_schedule_cache
async def from_bitrix_schedule(schedule_id: str | int = None) -> Schedule:
    """
    Получает информацию по указанному расписанию и возвращает ее в виде объекта Schedule
    """
    if schedule_id is None:
        schedule_id = SCHEDULE_ID
    schedule_data = await get_work_schedule(schedule_id)
    schedule = Schedule()
    # Дополнительные выходные
    current_calendar = schedule_data.get("EXCLUSIONS", {})
    exclusions_data = current_calendar.get("EXCLUSIONS", {})
    for _, months in exclusions_data.items():
        for month, days in months.items():
            for day, value in days.items():
                if value == "0":  # Выходной
                    schedule.exclusions.add(f"{day.zfill(2)}.{month}")
    # Рабочий день
    try:
        shifts = schedule_data["SHIFTS"][0]
        schedule.work_days = shifts["WORK_DAYS"]
        schedule.work_time_start = timedelta(seconds=shifts["WORK_TIME_START"])
        schedule.work_time_end = timedelta(seconds=shifts["WORK_TIME_END"])
        schedule.work_day_duration = schedule.work_time_end - schedule.work_time_start
    except:
        pass
    return schedule
