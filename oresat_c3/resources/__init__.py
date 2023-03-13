from olaf import app


def soft_reset():
    '''Restart OLAF daemon'''
    app.stop()


def hard_reset():
    '''Reboot system'''
    return  # TODO


def factory_reset():
    '''Clear FRAM and reboot system'''
    return  # TODO
