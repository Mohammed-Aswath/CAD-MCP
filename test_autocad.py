import win32com.client

acad = win32com.client.Dispatch("AutoCAD.Application")

print("Connected to AutoCAD")

doc = acad.ActiveDocument

print("Drawing:", doc.Name)

msp = doc.ModelSpace

print("ModelSpace accessed successfully")