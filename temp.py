class A:
    def __init__(self):
        print(self.__class__.__name__)

class B(A):
    def __init__(self):
        super().__init__()


if __name__ == "__main__":

    myClass = B()