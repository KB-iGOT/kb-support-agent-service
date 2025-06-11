
import logging
import os
import time

LOGGING_FORMAT = (
    '%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
)

def log_to_stdio(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format=LOGGING_FORMAT
    )


def log_to_folder(
    level=logging.INFO,
    *,
    sub_folder: str = 'agents_log',
    log_file_prefix: str = 'agent',
    log_file_timestamp: str = time.strftime('%Y%m%d_%H%M%S'),
):
  """Logs to system temp folder, instead of logging to stderr.

  Args
    sub_folder: str = 'agents_log',
    log_file_prefix: str = 'agent',
    log_file_timestamp: str = time.strftime('%Y%m%d_%H%M%S'),

  Returns
    the log file path.
  """
  log_dir = os.path.join(os.getcwd(), sub_folder)
  log_filename = f'{log_file_prefix}.{log_file_timestamp}.log'
  log_filepath = os.path.join(log_dir, log_filename)

  os.makedirs(log_dir, exist_ok=True)

  file_handler = logging.FileHandler(log_filepath, mode='w')
  file_handler.setLevel(level)
  file_handler.setFormatter(logging.Formatter(LOGGING_FORMAT))

  root_logger = logging.getLogger()
  root_logger.setLevel(level)
  root_logger.handlers = []  # Clear handles to disable logging to stderr
  root_logger.addHandler(file_handler)

  print(f'Log setup complete: {log_filepath}')

  latest_log_link = os.path.join(log_dir, f'{log_file_prefix}.latest.log')
  if os.path.islink(latest_log_link):
    os.unlink(latest_log_link)
  os.symlink(log_filepath, latest_log_link)

  print(f'To access latest log: tail -F {latest_log_link}')
  return log_filepath
