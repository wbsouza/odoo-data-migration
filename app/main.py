import configparser
import os
import logging


from migration.core.odoo import OdooConnection
from migration.executor import Migration

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def get_configs(configs_filename: str="./migration.conf"):
    configs = configparser.ConfigParser()
    configs.read(configs_filename)
    return configs


# Initialize logger
def setup_logging(configs: configparser.ConfigParser):
    """
    Setup logging configuration.
    :param configs: The app configs.
    :param log_file: Path to the log file.
    :param log_level: Logging level (e.g., INFO, DEBUG, ERROR).
    """
    # Setup logging from config
    log_file = configs.get('settings', 'log_file', fallback='./logs/migration.log')
    log_level = configs.get('settings', 'log_level', fallback='info').upper()
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    logging.basicConfig(
        filename=log_file,
        level=getattr(logging, log_level, logging.INFO),
        format='%(asctime)s %(levelname)s %(message)s',
    )

    # Create a file handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(log_level)

    # Create a console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)

    # Set up logging format
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    # Get the root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # Add handlers to the logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.info(f"Logging initialized: {log_file} at level {log_level}")


def main():
    """
    Main entry point for the migration script.
    """

    try:
        # Initialize source and destination Odoo connections from the config file
        configs = get_configs(f"{_BASE_DIR}/migration.conf")
        setup_logging(configs)
        logging.info("Starting the Odoo migration process...")

        src_odoo = OdooConnection(configs, connection_type="source")
        dst_odoo = OdooConnection(configs, connection_type="destination")

        # Connect to both Odoo instances
        src_odoo.connect()
        dst_odoo.connect()
    except Exception as e:
        logging.error(f"Failed to initialize Odoo connections: {str(e)}")
        return

    # Create the Migration instance
    mappings_dir = f"{_BASE_DIR}/mappings"
    migration = Migration(configs, src_odoo, dst_odoo, mappings_dir)

    # Start the migration process
    migration.run()


if __name__ == "__main__":
    main()
