from .logger import logging
import inspect


class BaashaError(Exception):
    def __init__(self, err) -> None:
        self.err = err

    def __str__(self):
        return self.err


# exception handler decorator
def raise_ctx_errors(func):
    def decorated(*args, **kwargs):
        try:
            return func(*args, **kwargs)

        except BaashaError as e:
            raise e

        except Exception as e:
            err = f"\n file: {inspect.getfile(func)} \n function: {func.__name__} \n error: {str(e)} \n\n"
            logging.error(err)
            raise BaashaError(err)

    return decorated


def log_ctx_errors(func):
    def decorated(*args, **kwargs):
        try:
            return func(*args, **kwargs)

        except BaashaError as e:
            logging.warning(
                f"Handled BaashaError in '{func.__name__}', returning None. "
                f"Original error: {e}"
            )
            return None

        except Exception as e:
            err = f"\n file: {inspect.getfile(func)} \n function: {func.__name__} \n error: {str(e)} \n\n"
            logging.error(err)
            return None

    return decorated


def propogate_ctx_errors(func):
    def decorated(*args, **kwargs):
        try:
            return (func(*args, **kwargs), None)

        except BaashaError as e:
            logging.warning(
                f"Observed BaashaError from '{func.__name__}'. Original error: {e}"
            )
            return (None, str(e))

        except Exception as e:
            err = f"\n file: {inspect.getfile(func)} \n function: {func.__name__} \n error: {str(e)} \n\n"
            logging.error(err)
            return (None, err)

    return decorated
