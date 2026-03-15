import functools

def trace(func):
    """
    Decorator that logs entry and exit of the decorated function at DEBUG level.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # In a class method, args[0] is typically 'self'. We can avoid printing the whole object.
        class_name = ""
        if args and hasattr(args[0], '__class__'):
            class_name = f"{args[0].__class__.__name__}."
            
        logger = None
        if hasattr(args[0], 'logger'):
            logger = args[0].logger

        if logger:
            logger.debug(f"ENTRY: {class_name}{func.__name__} | args: {args[1:]} kwargs: {kwargs}")
        
        try:
            result = func(*args, **kwargs)
            if logger:
                logger.debug(f"EXIT : {class_name}{func.__name__} | returned: {result}")
            return result
        except Exception as e:
            if logger:
                logger.debug(f"EXIT (EXCEPTION): {class_name}{func.__name__} | raised {type(e).__name__}: {e}")
            raise
    return wrapper
