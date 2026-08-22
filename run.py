import logging
import traceback
from datetime import datetime
from stockSender import job

logging.basicConfig(
    filename="stock_sender.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

if __name__ == "__main__":
    logging.info("Starting daily market email job")
    try:
        job()
        logging.info("Job completed successfully")
    except Exception:
        logging.error("Job failed:\n" + traceback.format_exc())
