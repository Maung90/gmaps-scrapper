"""Manajemen thread pool executor untuk job background."""

from concurrent.futures import ThreadPoolExecutor


def create_executor(max_workers: int = 2) -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="apify-job")
