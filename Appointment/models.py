from django.db import models

from django.db.models.signals import pre_delete
from django.dispatch import receiver

# mysql> create database yuanpei_underground charset=utf8mb4;
# > python manage.py makemigrations
# > python manage.py migrate
# Django会给没有自增字段的表默认添加自增字段（id）

class College_Announcement(models.Model):
    class Show_Status(models.IntegerChoices):
        Yes = 1
        No = 0
    
    show = models.SmallIntegerField('是否显示',
                                       choices=Show_Status.choices,
                                       default=0)
    announcement = models.CharField('通知内容',max_length=256,null=True)

    class Meta:
        verbose_name = "全院公告"
        verbose_name_plural = verbose_name

class Student(models.Model):
    Sid = models.CharField('学号', max_length=10, primary_key=True)
    Sname = models.CharField('姓名', max_length=64)
    Scredit = models.IntegerField('信用分', default=3)
    superuser = models.IntegerField('超级用户', default=0)
    pinyin = models.CharField('拼音', max_length=20, null=True)

    class Meta:
        verbose_name = '学生'
        verbose_name_plural = verbose_name
        ordering = ['Sid']


class RoomManager(models.Manager):
    def permitted(self):
        return self.filter(Rstatus=Room.Status.PERMITTED)


class Room(models.Model):
    # 房间编号我不确定是否需要。如果地下室有门牌的话（例如B101）保留房间编号比较好
    # 如果删除Rid记得把Rtitle设置成主键
    Rid = models.CharField('房间编号', max_length=8, primary_key=True)
    Rtitle = models.CharField('房间名称', max_length=32)
    Rmin = models.IntegerField('房间预约人数下限', default=0)
    Rmax = models.IntegerField('房间使用人数上限', default=20)
    Rstart = models.TimeField('最早预约时间')
    Rfinish = models.TimeField('最迟预约时间')
    Rlatest_time = models.DateTimeField("摄像头心跳",auto_now_add=True)
    Rpresent = models.IntegerField('目前人数',default=0)

    # Rstatus 标记当前房间是否允许预约，可由管理员修改
    class Status(models.IntegerChoices):
        PERMITTED = 0  # 允许预约
        SUSPENDED = 1  # 暂定使用
        # FORBIDDEN = 2  # 禁止使用

    Rstatus = models.SmallIntegerField('房间状态',
                                       choices=Status.choices,
                                       default=0)

    objects = RoomManager()

    class Meta:
        verbose_name = '房间'
        verbose_name_plural = verbose_name
        ordering = ['Rid']

    def __str__(self):
        return self.Rid + ' ' + self.Rtitle


class AppointManager(models.Manager):
    def not_canceled(self):
        return self.exclude(Astatus=Appoint.Status.CANCELED)


class Appoint(models.Model):
    Aid = models.AutoField('预约编号', primary_key=True)
    # 申请时间为插入数据库的时间
    Atime = models.DateTimeField('申请时间', auto_now_add=True)
    Astart = models.DateTimeField('开始时间')
    Afinish = models.DateTimeField('结束时间')
    Ausage = models.CharField('用途', max_length=256,null=True)
    Aannouncement = models.CharField('预约通知',max_length=256,null=True,blank=True)
    Anon_yp_num = models.IntegerField("外院人数",default=0)
    Ayp_num = models.IntegerField('院内人数',default=0)

    # 这里Room使用外键的话只能设置DO_NOTHING，否则删除房间就会丢失预约信息
    # 所以房间信息不能删除，只能逻辑删除
    # 调用时使用appoint_obj.Room和room_obj.appoint_list
    Room = models.ForeignKey(Room,
                             related_name='appoint_list',
                             null=True,
                             on_delete=models.SET_NULL,
                             verbose_name='房间号')
    students = models.ManyToManyField(Student, related_name='appoint_list',db_index=True)
    major_student = models.ForeignKey(Student,on_delete=models.CASCADE,verbose_name='Appointer',null=True)

    class Status(models.IntegerChoices):
        CANCELED = 0  # 已取消
        APPOINTED = 1  # 预约中
        PROCESSING = 2  # 进行中
        WAITING = 3  # 等待确认
        CONFIRMED = 4  # 已确认
        VIOLATED = 5  # 违约
        JUDGED = 6  # 违约申诉成功

    Astatus = models.IntegerField('预约状态',
                                  choices=Status.choices,
                                  default=1)

    # modified by wxy
    Acamera_check_num = models.IntegerField('检查次数',default=0)
    Acamera_ok_num = models.IntegerField('人数合格次数',default=0)

    class Reason(models.IntegerChoices):
        R_NOVIOLATED = 0 # 没有违约
        R_LATE = 1 # 迟到
        R_TOOLITTLE = 2 # 人数不足
        R_ELSE = 3 # 其它原因

    Areason = models.IntegerField('违约原因',
                                  choices=Reason.choices,
                                  default=0)
    # end

    objects = AppointManager()

    def cancel(self):
        self.Astatus = Appoint.Status.CANCELED
        self.students.clear()
        self.save()

    class Meta:
        verbose_name = '预约信息'
        verbose_name_plural = verbose_name
        ordering = ['Aid']

    def get_status(self):
        status = ""
        if self.Astatus == Appoint.Status.APPOINTED:
            status = "已预约"
        elif self.Astatus == Appoint.Status.CANCELED:
            status = "已取消"
        elif self.Astatus == Appoint.Status.PROCESSING:
            status = "进行中"
        elif self.Astatus == Appoint.Status.WAITING:
            status = "等待确认"
        elif self.Astatus == Appoint.Status.CONFIRMED:
            status = "已确认"
        elif self.Astatus == Appoint.Status.VIOLATED:
            if self.Areason == Appoint.Reason.R_NOVIOLATED:
                status = "未知错误,请联系管理员 "
            elif self.Areason == Appoint.Reason.R_LATE:
                status = "使用迟到"
            elif self.Areason == Appoint.Reason.R_TOOLITTLE:
                status = "人数不足"
            elif self.Areason == Appoint.Reason.R_ELSE:
                status = "管理员操作,请与管理员联系"
        elif self.Astatus == Appoint.Status.JUDGED:
            status = "申诉成功"
        return status


    def toJson(self):
        data = {
            'Aid':
            self.Aid,  # 预约编号
            'Atime':
            self.Atime,  # 申请提交时间
            'Astart':
            self.Astart,  # 开始使用时间
            'Afinish':
            self.Afinish,  # 结束使用时间
            'Ausage':
            self.Ausage,  # 房间用途
            'Aannouncement':
            self.Aannouncement, # 预约通知
            'Astatus':
            self.get_Astatus_display(),  # 预约状态
            'Areason':
            self.Areason,
            'Rid':
            self.Room.Rid,  # 房间编号
            'Rtitle':
            self.Room.Rtitle,  # 房间名称
            'yp_num':
            self.Ayp_num,   #院内人数
            'non_yp_num':
            self.Anon_yp_num,   #外院人数
            'major_student':
            {
                "Sname": self.major_student.Sname, # 发起预约人
                "Sid": self.major_student.Sid,
            },
            'students': [  # 参与人
                {
                    'Sname': student.Sname,  # 参与人姓名
                    'Sid': student.Sid,
                } for student in self.students.all() if Student.Sid != self.major_student.Sid
            ]
        }
        try:
            data['Rid'] = self.Room.Rid  # 房间编号
            data['Rtitle'] = self.Room.Rtitle  # 房间名称
        except Exception:
            data['Rid'] = 'deleted'  # 房间编号
            data['Rtitle'] = '房间已删除'  # 房间名称
        return data

from Appointment.utils.scheduler_func import cancel_scheduler
@receiver(pre_delete,sender=Appoint)
def before_delete_Appoint(sender,instance,**kwargs):
    cancel_scheduler(instance.Aid)