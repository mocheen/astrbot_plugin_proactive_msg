"""
调度器管理模块
负责主动消息插件的定时任务管理
"""
import asyncio
from typing import Callable, Any, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from astrbot.api import logger


class SchedulerManager:
    """定时任务调度器管理器"""

    def __init__(self, context, config: dict):
        self.context = context
        self.config = config
        self.scheduler: Optional[AsyncIOScheduler] = None
        # 使用AstrBot提供的logger
        self.logger = logger
        self.jobs: list = []

    async def start(self):
        """启动调度器"""
        try:
            if self.scheduler is None:
                self.scheduler = AsyncIOScheduler()
                self.scheduler.start()
                self.logger.info("调度器已启动")
            else:
                self.logger.warning("调度器已经在运行中")
        except Exception as e:
            self.logger.error(f"启动调度器失败: {e}")
            raise

    async def stop(self):
        """停止调度器"""
        try:
            if self.scheduler:
                self.scheduler.shutdown()
                self.scheduler = None
                self.logger.info("调度器已停止")
        except Exception as e:
            self.logger.error(f"停止调度器失败: {e}")
            raise

    def add_job(self, func: Callable, interval: str):
        """添加定时任务

        Args:
            func: 要执行的函数
            interval: 时间间隔，支持 '5min', '10min', '30min', '1hour', '3hour'
        """
        try:
            if not self.scheduler:
                raise RuntimeError("调度器未启动")

            # 将字符串间隔转换为秒数
            interval_seconds = self._parse_interval(interval)

            # 添加任务
            job = self.scheduler.add_job(
                func,
                'interval',
                seconds=interval_seconds,
                id=f'proactive_msg_job_{len(self.jobs)}',
                max_instances=1,
                misfire_grace_time=30
            )

            self.jobs.append(job)
            self.logger.info(f"已添加定时任务，间隔: {interval} ({interval_seconds}秒)")

        except Exception as e:
            self.logger.error(f"添加定时任务失败: {e}")
            raise

    def remove_job(self, job_id: str):
        """移除定时任务"""
        try:
            if self.scheduler:
                self.scheduler.remove_job(job_id)
                self.logger.info(f"已移除定时任务: {job_id}")
        except Exception as e:
            self.logger.error(f"移除定时任务失败: {e}")

    def _parse_interval(self, interval: str) -> int:
        """将时间间隔字符串转换为秒数"""
        interval_mapping = {
            '5min': 5 * 60,
            '10min': 10 * 60,
            '30min': 30 * 60,
            '1hour': 60 * 60,
            '3hour': 3 * 60 * 60
        }

        if interval in interval_mapping:
            return interval_mapping[interval]

        # 默认10分钟
        return 10 * 60

    def get_jobs_info(self) -> list:
        """获取所有任务信息"""
        if not self.scheduler:
            return []

        jobs_info = []
        for job in self.jobs:
            if job:
                jobs_info.append({
                    'id': job.id,
                    'next_run': job.next_run_time,
                    'interval': job.trigger.interval
                })

        return jobs_info

    def pause_job(self, job_id: str):
        """暂停任务"""
        try:
            if self.scheduler:
                self.scheduler.pause_job(job_id)
                self.logger.info(f"已暂停任务: {job_id}")
        except Exception as e:
            self.logger.error(f"暂停任务失败: {e}")

    def resume_job(self, job_id: str):
        """恢复任务"""
        try:
            if self.scheduler:
                self.scheduler.resume_job(job_id)
                self.logger.info(f"已恢复任务: {job_id}")
        except Exception as e:
            self.logger.error(f"恢复任务失败: {e}")

    def clear_all_jobs(self):
        """清除所有任务"""
        try:
            if self.scheduler:
                self.scheduler.remove_all_jobs()
                self.jobs = []
                self.logger.info("已清除所有任务")
        except Exception as e:
            self.logger.error(f"清除所有任务失败: {e}")

    def __del__(self):
        """析构函数，确保调度器被正确关闭"""
        if self.scheduler:
            try:
                self.scheduler.shutdown(wait=False)
            except Exception as e:
                # 在析构函数中无法使用异步日志，所以使用print
                print(f"关闭调度器时出现错误: {e}")