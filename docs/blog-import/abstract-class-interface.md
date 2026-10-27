---
title: "abstract-class-interface"
publishDate: "2024-02-24 10:00:00"
img: /tymultiverse/assets/java.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: A comprehensive comparison between abstract classes and interfaces in Java.
category: Java
tags:
  - Java
  - Abstract Class
  - Interface
---

# Abstract Classes vs Interfaces in Java

## Overview

本文件深入比較了 Java 中的抽象類別與介面，介紹了各自的特性、使用情境以及實作示例，方便您根據需求選擇合適的設計方法。

## Abstract Classes

抽象類別可以同時包含抽象方法與實體方法，子類別可選擇性地覆寫抽象方法而不必覆寫實體方法。

### Example

```java
abstract class User {
    abstract void displayInfo();

    void greet() {
        System.out.println("Hello!");
    }
}

class AdminUser extends User {
    @Override
    void displayInfo() {
        System.out.println("Admin User");
    }
}
```

若子類別尚未覆寫所有抽象方法，則子類本身也必須聲明為抽象類別：

```java
abstract class Ghost extends User {
    // 額外定義一個抽象方法
    abstract void haunt();
    // 無需覆寫 greet() 方法
}
```

#### Main 方法示例

```java
public class Main {
    public static void main(String[] args) {
        AdminUser admin = new AdminUser();
        admin.greet();        // 輸出: Hello!
        admin.displayInfo();  // 輸出: Admin User
    }
}
```

## Interfaces

介面定義了一組合約，各個類別通過實作介面來提供具體行為。自 Java 8 以後，介面也支援 default 方法，允許直接在介面中定義預設實作。

### Example

```java
interface Walker {
    void walk();

    default void breathe() {
        System.out.println("Breathing...");
    }
}
```

實作介面的類別：

```java
class Human implements Walker {
    // 可視需求覆寫 walk() 方法
}

class Dog implements Walker {
    @Override
    public void walk() {
        System.out.println("Dog is walking");
    }
}

public class Main {
    public static void main(String[] args) {
        Human human = new Human();
        human.walk();    // 使用介面預設或自行實作
        human.breathe(); // 輸出: Breathing...

        Dog dog = new Dog();
        dog.walk();      // 輸出: Dog is walking
    }
}
```

## Inheritance and Polymorphism

### 利用抽象類別實現多型

抽象類別允許子類別共享通用行為並覆寫專屬功能：

```java
abstract class Animal {
  public abstract void makeSound(); // 抽象方法

  public void eat() {
      System.out.println("The animal is eating");
  }
}
```

### 利用介面實現多重繼承

介面允許一個類別實作多個介面，從而組合多種行為：

```java
interface AnimalMovement {
  void walk();
}

class Dog implements AnimalMovement {
  @Override
  public void walk(){
    System.out.println("Dog is walking");
  }
}
```

