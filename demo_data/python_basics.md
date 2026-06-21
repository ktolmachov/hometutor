# Python Basics

Python is a high-level programming language known for its simplicity and readability.

## Variables and Data Types

Python supports several data types:
- **int** - integers (42, -10, 1000)
- **float** - floating point numbers (3.14, -0.5)
- **str** - strings ("hello", 'world')
- **bool** - boolean values (True, False)

## Control Flow

### If Statements

```python
if x > 0:
    print("positive")
elif x < 0:
    print("negative")
else:
    print("zero")
```

### Loops

For loops iterate over sequences:
```python
for item in items:
    print(item)
```

While loops run while a condition is true:
```python
while count < 10:
    count += 1
```

## Functions

Functions are defined with the `def` keyword:

```python
def greet(name):
    return f"Hello, {name}!"
```