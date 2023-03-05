import os

from olaf import olaf_run


def main():
    olaf_run(f'{os.path.dirname(os.path.abspath(__file__))}/data/oresat_c3.dcf')


if __name__ == '__main__':
    main()
